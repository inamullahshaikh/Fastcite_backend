# database/auth.py
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from datetime import datetime
from jose import JWTError, jwt
from passlib.context import CryptContext
from typing import Optional
from uuid import uuid4
import os
from fastapi.responses import RedirectResponse, JSONResponse
from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request
from dotenv import load_dotenv
from database.mongo import users_collection
# Load .env (if present)
load_dotenv()

# ==============================
# CONFIGURATION
# ==============================
router = APIRouter(prefix="/auth", tags=["Authentication"])

# JWT Config (permanent login — no expiry)
SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey")
ALGORITHM = "HS256"

# Password Hashing (Argon2)
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

# OAuth2 Scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Ensure backend/frontend urls exist (use defaults if not provided)
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

# Validate critical Google env vars early (fail fast)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
    # If you want the app to run *without* Google enabled, remove/adjust this raise.
    raise RuntimeError(
        "Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET environment variables. "
        "Add them to your .env or environment."
    )

# ==============================
# Pydantic Models
# ==============================
class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    name: str
    dob: Optional[str] = None
    role: Optional[str] = "user"

class Token(BaseModel):
    access_token: str
    token_type: str

# ==============================
# Helper Functions
# ==============================
def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict):
    """Permanent token (no expiration)"""
    # add issued-at time for better introspection
    payload = data.copy()
    payload["iat"] = int(datetime.utcnow().timestamp())
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

# ==============================
# AUTH ROUTES
# ==============================
@router.post("/signup", status_code=201)
async def signup(user: UserCreate):
    existing_user = await users_collection.find_one(
        {"$or": [{"username": user.username}, {"email": user.email}]}
    )
    if existing_user:
        raise HTTPException(status_code=400, detail="Username or email already registered")

    user_dict = {
        "id": str(uuid4()),
        "username": user.username,
        "pass_hash": hash_password(user.password),
        "name": user.name,
        "dob": user.dob,
        "email": user.email,
        "role": user.role,
        "created_at": datetime.utcnow(),
    }

    await users_collection.insert_one(user_dict)
    return {"message": "User created successfully"}

@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await users_collection.find_one({"username": form_data.username})
    if not user or not verify_password(form_data.password, user["pass_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Include username + role in token
    token_data = {
        "sub": user["username"],
        "role": user["role"],
        "id": user["id"],
    }
    access_token = create_access_token(token_data)
    return {"access_token": access_token, "token_type": "bearer"}

# ==============================
# CURRENT USER DEPENDENCY
# ==============================
async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = await users_collection.find_one({"username": username})
    if user is None:
        raise credentials_exception

    user["role"] = role
    return user

# ==============================
# GOOGLE OAUTH SETUP
# ==============================
oauth = OAuth()
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# ==============================
# GOOGLE LOGIN ROUTES
# ==============================
@router.get("/google/login")
async def google_login(request: Request):
    """
    Step 1: Redirect user to Google login page
    """
    # BACKEND_URL is guaranteed to be a string (defaulted above)
    redirect_uri = f"{BACKEND_URL}/auth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)

@router.get("/google/callback")
async def google_callback(request: Request):
    """
    Step 2: Handle Google's callback, create/find user, issue JWT
    """
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error obtaining access token: {e}")

    # Try common places for user info
    user_info = None
    # Some providers return userinfo in token['userinfo'], some require userinfo endpoint call
    if isinstance(token, dict):
        user_info = token.get("userinfo") or token.get("id_token_claims") or None

    # Fallback: call userinfo endpoint directly
    if not user_info:
        try:
            # authlib exposes `.userinfo()` convenience on the remote app in many versions
            # but to be broadly compatible, attempt `.userinfo()` then `.get('userinfo')` fallback.
            user_info = await oauth.google.userinfo(token=token)
        except Exception:
            # final fallback: try a raw GET to the userinfo endpoint
            try:
                resp = await oauth.google.get("userinfo", token=token)
                user_info = resp.json() if resp and resp.status_code == 200 else None
            except Exception:
                user_info = None

    if not user_info or "email" not in user_info:
        # Return an explicit failure that frontend can handle
        return JSONResponse(
            status_code=400,
            content={"detail": "Google login failed: could not obtain user info"},
        )

    email = user_info["email"]
    name = user_info.get("name", email.split("@")[0])
    google_id = user_info.get("sub") or user_info.get("id")  # different providers use different keys

    # Check if user already exists
    existing_user = await users_collection.find_one({"email": email})

    if not existing_user:
        # Create new user
        new_user = {
            "id": str(uuid4()),
            "username": email.split("@")[0],
            "email": email,
            "name": name,
            "role": "user",
            "google_id": google_id,
            "created_at": datetime.utcnow(),
        }
        await users_collection.insert_one(new_user)
        user = new_user
    else:
        # Optionally update google_id if missing
        if google_id and existing_user.get("google_id") != google_id:
            await users_collection.update_one(
                {"_id": existing_user["_id"]},
                {"$set": {"google_id": google_id}}
            )
        user = existing_user

    # Create JWT for our app
    token_data = {"sub": user["username"], "role": user["role"]}
    access_token = create_access_token(token_data)

    # Redirect to frontend with token
# Redirect to frontend callback route with token
    frontend_url = f"{FRONTEND_URL.rstrip('/')}/auth/google/callback?token={access_token}"
    return RedirectResponse(url=frontend_url)

