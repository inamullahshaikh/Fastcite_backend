from fastapi import APIRouter, Depends, HTTPException
from typing import List
from database.auth import get_current_user
from database.mongo import books_collection
from database.models import Book

router = APIRouter(prefix="/books", tags=["Books"])

# ----------------------------
# CREATE BOOK (any logged user)
# ----------------------------
@router.post("/", status_code=201)
async def upload_book(book: Book, current_user: dict = Depends(get_current_user)):
    data = book.dict()
    data["uploader_id"] = str(current_user["id"])
    await books_collection.insert_one(data)  # async insert
    return {"message": "Book uploaded successfully"}

# ----------------------------
# GET ALL (admin)
# ----------------------------
@router.get("/", response_model=List[Book])
async def get_all_books(current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    cursor = books_collection.find({}, {"_id": 0})
    books = await cursor.to_list(length=1000)  # convert async cursor to list
    return books

# ----------------------------
# GET MY BOOKS (self)
# ----------------------------
@router.get("/me", response_model=List[Book])
async def get_my_books(current_user: dict = Depends(get_current_user)):
    cursor = books_collection.find(
        {"uploaded_by": str(current_user["id"])}, {"_id": 0}
    )
    raw_books = await cursor.to_list(length=1000)

    books = [
        Book(
            id=b.get("id"),
            title=b.get("title", ""),
            author_name=b.get("author_name"),
            pages=b.get("pages"),
            status=b.get("status", "processing"),
            uploaded_at=b.get("uploaded_at"),
            uploaded_by=b.get("uploaded_by", []),
        )
        for b in raw_books
    ]

    return books

# ----------------------------
# UPDATE BOOK (admin or uploader)
# ----------------------------
@router.put("/{book_id}")
async def update_book(book_id: str, updates: dict, current_user: dict = Depends(get_current_user)):
    book = await books_collection.find_one({"id": book_id})
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if current_user["role"] != "admin" and book["uploader_id"] != str(current_user["id"]):
        raise HTTPException(status_code=403, detail="Access denied")

    await books_collection.update_one({"id": book_id}, {"$set": updates})
    return {"message": "Book updated successfully"}

# ----------------------------
# DELETE BOOK (admin or uploader)
# ----------------------------
@router.delete("/{book_id}")
async def delete_book(book_id: str, current_user: dict = Depends(get_current_user)):
    book = await books_collection.find_one({"id": book_id})
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if current_user["role"] != "admin" and book["uploader_id"] != str(current_user["id"]):
        raise HTTPException(status_code=403, detail="Access denied")

    await books_collection.delete_one({"id": book_id})
    return {"message": "Book deleted successfully"}
