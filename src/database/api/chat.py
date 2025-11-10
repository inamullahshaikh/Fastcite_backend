from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from uuid import uuid4, UUID
from datetime import datetime
from pydantic import BaseModel, Field
from database.auth import get_current_user
from database.mongo import chat_sessions_collection
from database.models import ChatSession, ChatMessage
router = APIRouter(prefix="/chats", tags=["Chat Sessions"])

# ----------------------------
# CREATE (self or admin)
# ----------------------------
@router.post("/", status_code=201)
async def create_chat(session: ChatSession, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin" and str(current_user["id"]) != str(session.user_id):
        raise HTTPException(status_code=403, detail="Cannot create session for another user")

    await chat_sessions_collection.insert_one(session.to_mongo())
    return {"message": "Chat session created successfully"}

# ----------------------------
# GET ALL (admin)
# ----------------------------
@router.get("/", response_model=List[ChatSession])
async def get_all(current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    cursor = chat_sessions_collection.find({}, {"_id": 0})
    chats = await cursor.to_list(length=1000)
    return chats

# ----------------------------
# GET MINE (self)
# ----------------------------
@router.get("/me", response_model=List[ChatSession])
async def get_my_chats(current_user: dict = Depends(get_current_user)):
    cursor = chat_sessions_collection.find({"user_id": str(current_user["id"])}, {"_id": 0})
    chats = await cursor.to_list(length=1000)
    return chats

# ----------------------------
# GET BY ID (admin or self)
# ----------------------------
@router.get("/{chat_id}", response_model=ChatSession)
async def get_chat(chat_id: str, current_user: dict = Depends(get_current_user)):
    chat = await chat_sessions_collection.find_one({"id": chat_id}, {"_id": 0})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    if current_user["role"] != "admin" and str(chat["user_id"]) != str(current_user["id"]):
        raise HTTPException(status_code=403, detail="Access denied")
    return chat

# ----------------------------
# APPEND MESSAGE
# ----------------------------
@router.post("/{chat_id}/message")
async def add_message(chat_id: str, message: ChatMessage, current_user: dict = Depends(get_current_user)):
    chat = await chat_sessions_collection.find_one({"id": chat_id})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    if current_user["role"] != "admin" and str(chat["user_id"]) != str(current_user["id"]):
        raise HTTPException(status_code=403, detail="Access denied")

    await chat_sessions_collection.update_one(
        {"id": chat_id},
        {
            "$push": {"messages": message.dict()},
            "$set": {"updated_at": datetime.utcnow()}
        }
    )
    return {"message": "Message added successfully"}

# ----------------------------
# DELETE CHAT
# ----------------------------
@router.delete("/{chat_id}")
async def delete_chat(chat_id: str, current_user: dict = Depends(get_current_user)):
    chat = await chat_sessions_collection.find_one({"id": chat_id})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    if current_user["role"] != "admin" and str(chat["user_id"]) != str(current_user["id"]):
        raise HTTPException(status_code=403, detail="Access denied")

    await chat_sessions_collection.delete_one({"id": chat_id})
    return {"message": "Chat deleted successfully"}
