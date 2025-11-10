# database/mongo.py
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os

# Load environment variables from .env
load_dotenv()

# MongoDB connection string
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "ai_project_db")

# Create async Mongo client and database
client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]

# Initialize collections
users_collection = db["users"]
chat_sessions_collection = db["chat_sessions"]
books_collection = db["books"]


