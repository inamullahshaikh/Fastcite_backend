import os
import uuid
import fitz
import concurrent.futures
from typing import List
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient, models
from b2sdk.v2 import InMemoryAccountInfo, B2Api
from celery_app.celery_app import celery_app
from database.mongo import books_collection  # This is assumed to be set up correctly
from datetime import datetime
from qdrant_client.http.exceptions import UnexpectedResponse
import re
import json
from app.helpers import *
from app.embedder import embedder

# ------------------ Celery Task (MODIFIED) ------------------ #
@celery_app.task(name="process_pdf_to_qdrant_task")
def process_pdf_task(pdf_path: str, user_id: str, batch_size: int = 50, workers: int = 6):
    """Background task to process a PDF, using global clients."""
    
    # --- Step 0: Check if global clients are available ---
    if not all([embedder, QDRANT_CLIENT, B2_UPLOADER]):
        raise EnvironmentError("One or more global clients (Model, Qdrant, B2) are not initialized.")
    
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"{pdf_path} not found.")

    # --- Clients are now used from the global scope ---
    # NO: embedder = Embedder()
    # NO: uploader = BackblazeUploader()
    # NO: qdrant = QdrantClient(url=qdrant_url)
    
    # --- Clients are now used from the global scope ---
    # NO: embedder = Embedder()
    # NO: uploader = BackblazeUploader()
    # NO: qdrant = QdrantClient(url=qdrant_url)
    
    collection_name = "pdf_chunks"

    # --- Step 1: Initialize Qdrant Collection ---
    existing = [c.name for c in QDRANT_CLIENT.get_collections().collections]
    existing = [c.name for c in QDRANT_CLIENT.get_collections().collections]
    if collection_name not in existing:
        QDRANT_CLIENT.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE),
        )
        print("✅ Qdrant collection created.")
    else:
        print("ℹ️ Using existing Qdrant collection.")

    # --- Step 2: Extract PDF Metadata ---
    doc = fitz.open(pdf_path)
    toc = doc.get_toc()
    if not toc:
        raise ValueError("No Table of Contents found in PDF.")

    title, author_name = extract_metadata(doc)
    pages = doc.page_count

    # --- Step 3: Check Mongo for existing book (using UUID) ---
    existing_book = books_collection.find_one({"title": title})

    # ... (rest of Step 3 logic is unchanged) ...
    # ... (rest of Step 3 logic is unchanged) ...
    if existing_book:
        print(f"📚 Book already exists: {title}")
        if "id" not in existing_book: 
            book_id = str(uuid.uuid4())
            books_collection.update_one({"_id": existing_book["_id"]},{"$set": {"id": book_id}})
            print(f"🔄 Migrated old book to UUID: {book_id}")
        else:
            book_id = existing_book["id"]
            book_id = existing_book["id"]
        
        if user_id not in existing_book.get("uploaded_by", []):
            books_collection.update_one(
                {"id": book_id},
                {"id": book_id},
                {"$addToSet": {"uploaded_by": user_id}}
            )
        # BUG FIX: You were returning `len(points)` here, but `points` wasn't defined.
        # It's better to just return a standard message.
        print(f"✅ Completed processing (existing book): {title} by {author_name}")
        return {"book_id": book_id, "title": title, "author_name": author_name, "chunks": 0, "status": "existing"}
        # BUG FIX: You were returning `len(points)` here, but `points` wasn't defined.
        # It's better to just return a standard message.
        print(f"✅ Completed processing (existing book): {title} by {author_name}")
        return {"book_id": book_id, "title": title, "author_name": author_name, "chunks": 0, "status": "existing"}
    else:
        print(f"🆕 New book detected: {title}")
        book_id = str(uuid.uuid4())
        new_book = {
            "id": book_id,
            "id": book_id,
            "title": title,
            "author_name": author_name,
            "pages": pages,
            "status": "processing",
            "uploaded_at": datetime.utcnow(),
            "uploaded_by": [user_id],
        }
        books_collection.insert_one(new_book)



    # --- Step 4: Run PDF Split + Upload + Qdrant logic ---
    # ... (logic is unchanged) ...
    # ... (logic is unchanged) ...
    pdf_dir = "pdfs"
    toc_tree = build_toc_tree(toc)
    leaf_nodes = collect_leaf_nodes(toc_tree)
    pdf_chunks = []

    def process_node(i):
        node = leaf_nodes[i]
        start_page = node["page"]
        end_page = leaf_nodes[i + 1]["page"] if i + 1 < len(leaf_nodes) else doc.page_count + 1
        text = extract_text_for_node(doc, start_page, end_page)
        if not text.strip():
            return None
        local_pdf_path, pdf_filename = save_mini_pdf(doc, start_page, end_page, pdf_dir, book_id)
        return {
            "title": node["title"],
            "path": " > ".join(node["path"]),
            "start_page": start_page,
            "end_page": end_page - 1,
            "local_path": local_pdf_path,
            "filename": pdf_filename,
            "text": text
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        for result in executor.map(process_node, range(len(leaf_nodes))):
            if result:
                pdf_chunks.append(result)


    # --- Step 5: Upload to Backblaze (using global B2_UPLOADER) ---

    # --- Step 5: Upload to Backblaze (using global B2_UPLOADER) ---
    def upload_one(i):
        chunk = pdf_chunks[i]
        file_info = {"book_id": book_id, "book_name": title, "author_name": author_name}
        return i, B2_UPLOADER.upload_one(chunk["local_path"], chunk["filename"], file_info)
        return i, B2_UPLOADER.upload_one(chunk["local_path"], chunk["filename"], file_info)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        all_urls = [url for _, url in executor.map(upload_one, range(len(pdf_chunks)))]

    valid_chunks = [c for c, u in zip(pdf_chunks, all_urls) if u]
    texts = [c["text"] for c in valid_chunks]
    
    # --- Use global MODEL ---
    vectors = embedder.embed_batch(texts, batch_size=batch_size, show_progress_bar=True)

    # --- Step 6: Push to Qdrant (using global QDRANT_CLIENT) ---
    points = []
    for chunk, vector, url in zip(valid_chunks, vectors, all_urls):
        payload = {
            "chunk_id": str(uuid.uuid4()),
            "book_id": book_id,
            "book_name": title,
            "author_name": author_name,
            "start_page": chunk["start_page"],
            "end_page": chunk["end_page"],
            "heading": chunk["title"],
            "path": chunk["path"],
            "content": chunk["text"],
            "content": chunk["text"],
            "source_pdf": url,
        }
        points.append(models.PointStruct(id=uuid.uuid4().int >> 64, vector=vector.tolist(), payload=payload))

    for i in range(0, len(points), batch_size):
        QDRANT_CLIENT.upsert(collection_name=collection_name, points=points[i:i + batch_size])
        QDRANT_CLIENT.upsert(collection_name=collection_name, points=points[i:i + batch_size])

    # --- Step 7: Update Mongo status (using UUID) ---
    books_collection.update_one(
        {"id": book_id},
        {"id": book_id},
        {"$set": {"status": "complete"}}
    )

    print(f"✅ Completed processing: {title} by {author_name}")
    return {"book_id": book_id, "title": title, "author_name": author_name, "chunks": len(points)}


# ------------------ DELETE TASKS (MODIFIED) ------------------ #
# ------------------ DELETE TASKS (MODIFIED) ------------------ #

@celery_app.task(name="delete_qdrant_chunks_task")
def delete_qdrant_chunks_task(book_id: str):
    """Deletes all chunks in Qdrant using the global client."""
    
    if not QDRANT_CLIENT:
        print("❌ Qdrant client not initialized. Cannot delete chunks.")
        return {"status": "failed", "error": "Qdrant client not initialized"}
        
def delete_qdrant_chunks_task(book_id: str):
    """Deletes all chunks in Qdrant using the global client."""
    
    if not QDRANT_CLIENT:
        print("❌ Qdrant client not initialized. Cannot delete chunks.")
        return {"status": "failed", "error": "Qdrant client not initialized"}
        
    collection_name = "pdf_chunks"

    try:
        print(f"🧹 Deleting Qdrant chunks for book_id={book_id}...")
        result = QDRANT_CLIENT.delete(
            collection_name=collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="book_id",
                            match=models.MatchValue(value=book_id)
                        )
                    ]
                )
            ),
        )
        print(f"✅ Deleted chunks from Qdrant for book_id={book_id}")
        return {"status": "success", "book_id": book_id}
    except Exception as e:
        print(f"❌ Failed to delete Qdrant chunks: {e}")
        return {"status": "failed", "error": str(e)}


@celery_app.task(name="delete_b2_pdfs_task")
def delete_b2_pdfs_task(book_id: str):
    """Deletes all mini-PDFs from Backblaze B2 using the global client."""
    
    if not B2_UPLOADER:
        print("❌ B2 Uploader not initialized. Cannot delete files.")
        return {"status": "failed", "error": "B2 Uploader not initialized"}


    try:
        print(f"🗑️ Deleting files from Backblaze B2 for book_id={book_id}...")

        deleted_count = 0
        # Use the global uploader's list_files method
        for file_info, _ in B2_UPLOADER.list_files():
            file_metadata = file_info.file_info if hasattr(file_info, 'file_info') else {}
            if file_metadata.get("book_id") == book_id:
                try:
                    # Use the global uploader's delete_file method
                    B2_UPLOADER.delete_file(file_info.id_, file_info.file_name)
                    # Use the global uploader's delete_file method
                    B2_UPLOADER.delete_file(file_info.id_, file_info.file_name)
                    print(f"✅ Deleted {file_info.file_name}")
                    deleted_count += 1
                except Exception as e:
                    print(f"⚠️ Failed to delete {file_info.file_name}: {e}")

        print(f"🧾 Completed cleanup for book_id={book_id}. Deleted {deleted_count} files.")
        return {"status": "success", "book_id": book_id, "deleted_count": deleted_count}

    except Exception as e:
        print(f"❌ Error deleting from B2: {e}")
        return {"status": "failed", "error": str(e)}


@celery_app.task(name="delete_book_task")
def delete_book_task(book_id: str, user_id: str):
    """Delete a book entry, with support for multi-user uploads."""
    
    book = books_collection.find_one({"id": book_id})
    book = books_collection.find_one({"id": book_id})
    if not book:
        return {"status": "not_found"}

    # If multiple users uploaded this book → only remove this user
    if len(book.get("uploaded_by", [])) > 1:
        books_collection.update_one(
            {"id": book_id},
            {"id": book_id},
            {"$pull": {"uploaded_by": user_id}}
        )
        print(f"👤 Removed user {user_id} from book {book_id}")
        return {"status": "user_removed_only", "book_id": book_id}

    # If single uploader → delete everywhere
    books_collection.delete_one({"id": book_id})
    
    # --- MODIFIED ---
    # Removed `qdrant_url` argument from the .delay() call
    delete_qdrant_chunks_task.delay(book_id)
    books_collection.delete_one({"id": book_id})
    
    # --- MODIFIED ---
    # Removed `qdrant_url` argument from the .delay() call
    delete_qdrant_chunks_task.delay(book_id)
    delete_b2_pdfs_task.delay(book_id)
    
    
    print(f"🧹 Deleted book {book_id} completely")
    return {"status": "fully_deleted", "book_id": book_id}


# ------------------ Google API CALL ------------------ #


@celery_app.task(name="tasks.search_similar_in_books", priority=10)
def search_similar_in_books_task(query_vec, book_id: str, top_k: int = 3):
    """Celery background task for searching across multiple books."""
    all_results = []
    try:
        all_results = search_similar_in_book(query_vec, book_id, top_k)
    except UnexpectedResponse as e:
        print(f"UnexpectedResponse: {e}")
    except Exception as e:
        print(f"Error in search_similar_in_books: {e}")

    all_results.sort(key=lambda x: x.get('score', 0) or 0, reverse=True)
    return all_results


@celery_app.task(name="tasks.select_top_contexts", priority=10)
def select_top_contexts_task(contexts: List[dict], user_query: str) -> List[str]:
    """Celery task: use Gemini to pick top 3 most relevant contexts."""
    context_list = []
    for i, c in enumerate(contexts):
        context_id = c.get('id', f'unknown_{i}')
        heading = c.get('heading', 'No heading')
        content = c.get('content', '')[:500]
        context_list.append(f"ID: {context_id}\nHeading: {heading}\nContent: {content}...\n")
    contexts_text = "\n---\n".join(context_list)

    selection_prompt = f"""
    You are given {len(contexts)} context passages and a user query.
    Select the TOP 3 most relevant context passages.

    USER QUERY: {user_query}

    AVAILABLE CONTEXTS:
    {contexts_text}

    Respond with ONLY JSON:
    {{"selected_ids": ["id1", "id2", "id3"]}}
    """

    try:
        response = client_genai.models.generate_content(
            model=AIMODEL,
            contents=[
                Content(role="model", parts=[Part(text="You are an expert at evaluating context relevance.")]),
                Content(role="user", parts=[Part(text=selection_prompt)])
            ]
        )
        cleaned = re.sub(r"^```json\s*|```$", "", response.text.strip(), flags=re.MULTILINE).strip()
        parsed = json.loads(cleaned)
        selected_ids = parsed.get("selected_ids", [])
        print("-----------------selected ids-------------------------")
        print(selected_ids)
        print("-----------------selected ids-------------------------")
        return selected_ids[:3] if len(selected_ids) >= 3 else selected_ids
    except Exception as e:
        print(f"Error selecting contexts: {e}")
        return [c.get('id') for c in contexts[:3]]


@celery_app.task(name="tasks.call_model", priority=10)
def call_model_task(full_prompt: str, system_prompt: str) -> tuple[str, str]:
    """Celery task: generate text using Gemini."""
    try:
        response = client_genai.models.generate_content(
            model=AIMODEL,
            contents=[
                Content(role="model", parts=[Part(text=system_prompt)]),
                Content(role="user", parts=[Part(text=full_prompt)])
            ]
        )
        answer = response.text.strip()
        return answer, "No reasoning available (Gemini API does not return reasoning steps)"
    except Exception as e:
        print(f"Error calling Gemini model: {e}")
        return f"Error: {str(e)}", "No reasoning available"


@celery_app.task(name="tasks.process_contexts_and_generate", priority=10)
def process_contexts_and_generate_task(contexts: List[dict], user_query: str):
    """Complete Celery pipeline: select top contexts + generate answer."""
    from celery_app.tasks import select_top_contexts_task, call_model_task  # local imports to avoid circular ref

    selection_contexts = contexts[:10]
    selected_ids = select_top_contexts_task(contexts, user_query)
    selected_contexts = [c for c in contexts if c.get('id') in selected_ids]

    context_text = "\n\n".join([f"### {c.get('heading','')}\n{c.get('content','')}" for c in selected_contexts])
    full_prompt = f"Use the following context to answer the question.\n\n{context_text}\n\n**User Question:** {user_query}"

    system_prompt = (
        "You are a knowledgeable AI assistant. Respond in clean Markdown with headings, bullet points, and summary."
    )

    answer, reasoning = call_model_task(full_prompt, system_prompt)
    return {
        "answer": answer,
        "reasoning": reasoning,
        "selected_ids": selected_ids,
        "selected_contexts": selected_contexts,
    }
