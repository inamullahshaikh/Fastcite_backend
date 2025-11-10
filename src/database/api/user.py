from fastapi import APIRouter, Depends, HTTPException
from pydantic import EmailStr
from typing import List, Optional, Literal
from uuid import uuid4, UUID
from datetime import datetime, date
from database.auth import get_current_user, users_collection

from pydantic import BaseModel, Field

router = APIRouter(prefix="/users", tags=["Users"])

class UserProfile(BaseModel):
    id: UUID
    username: str
    name: str
    dob: Optional[str] = None  # return ISO string for frontend
    email: EmailStr
    role: Literal["user", "admin"] = "user"

    class Config:
        from_attributes = True  # for Pydantic v2
        json_schema_extra = {
            "example": {
                "id": "3906100a-c589-4a10-be1a-c6d230533bf2",
                "username": "inam123",
                "name": "Inam Ullah",
                "dob": "2004-06-17",
                "email": "inam@example.com",
                "role": "user"
            }
        }
# ----------------------------
# USER PROFILE MODEL
# ----------------------------
class UserProfile(BaseModel):
    id: UUID
    username: str
    name: str
    dob: Optional[str] = None  # ISO string for frontend
    email: EmailStr
    role: Literal["user", "admin"] = "user"

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "3906100a-c589-4a10-be1a-c6d230533bf2",
                "username": "inam123",
                "name": "Inam Ullah",
                "dob": "2004-06-17",
                "email": "inam@example.com",
                "role": "user"
            }
        }

# ----------------------------
# USER MODEL
# ----------------------------
class User(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    username: str
    pass_hash: str
    name: str
    dob: Optional[date] = None
    email: EmailStr
    role: Literal["user", "admin"] = "user"

# ----------------------------
# CREATE USER (anyone)
# ----------------------------
@router.post("/", status_code=201)
async def create_user(user: User):
    existing_user = await users_collection.find_one({"email": user.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    data = user.dict()
    data["created_at"] = datetime.utcnow()
    await users_collection.insert_one(data)
    return {"message": "User created successfully"}

# ----------------------------
# GET ALL USERS (admin only)
# ----------------------------
@router.get("/", response_model=List[User])
async def get_all_users(current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    cursor = users_collection.find({}, {"_id": 0})
    users = await cursor.to_list(length=1000)
    return users

# ----------------------------
# GET USER BY ID (admin or self)
# ----------------------------
@router.get("/{user_id}", response_model=User)
async def get_user_by_id(user_id: str, current_user: dict = Depends(get_current_user)):
    user = await users_collection.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if current_user["role"] != "admin" and str(current_user["id"]) != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return user

# ----------------------------
# GET MY PROFILE
# ----------------------------
@router.get("/getmyprofile/me", response_model=UserProfile)
async def get_my_profile(current_user: dict = Depends(get_current_user)):
    dob_value = current_user.get("dob")
    # Ensure dob is string for frontend
    if isinstance(dob_value, (datetime, date)):
        dob = dob_value.isoformat()
    else:
        dob = dob_value
    return {
        "id": str(current_user.get("id") or current_user.get("_id")),
        "username": current_user.get("username"),
        "name": current_user.get("name"),
        "email": current_user.get("email"),
        "role": current_user.get("role", "user"),
        "dob": dob,
    }

# ----------------------------
# UPDATE USER (admin or self)
# ----------------------------
@router.put("/{user_id}")
async def update_user(user_id: str, updates: dict, current_user: dict = Depends(get_current_user)):
    user = await users_collection.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if current_user["role"] != "admin" and str(current_user["id"]) != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    protected = {"id", "email", "role"}
    updates = {k: v for k, v in updates.items() if k not in protected}
    await users_collection.update_one({"id": user_id}, {"$set": updates})
    return {"message": "User updated successfully"}

# ----------------------------
# DELETE USER (admin or self)
# ----------------------------
@router.delete("/{user_id}")
async def delete_user(user_id: str, current_user: dict = Depends(get_current_user)):
    user = await users_collection.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if current_user["role"] != "admin" and str(current_user["id"]) != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    await users_collection.delete_one({"id": user_id})
    return {"message": "User deleted successfully"}
