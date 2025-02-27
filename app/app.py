from flask import Flask, render_template, request, jsonify, session, Response, stream_with_context, redirect, url_for
from chromadb.utils import embedding_functions
import chromadb
import numpy
import os
from dotenv import load_dotenv
import chatbot
import pdf_upload

load_dotenv()

app = Flask(__name__)

UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER")
ALLOWED_EXTENSIONS = os.getenv("ALLOWED_EXTENSIONS")
app.config['UPLOAD_FOLDER'] = os.getenv("UPLOAD_FOLDER")

embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
client = chromadb.PersistentClient(path="chromaDB")
collection_name = "pdf_embeddings"
if collection_name not in client.list_collections():
    collection = client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=embedding_functions.SentenceTransformerEmbeddingFunction('all-MiniLM-L6-v2')
    )
else:
    collection = client.get_collection(
        name=collection_name,
        embedding_function=embedding_functions.SentenceTransformerEmbeddingFunction('all-MiniLM-L6-v2')
    )

@app.route("/")
def main():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload_file():
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    if 'file' not in request.files:
        return jsonify({"error": "Nenhum ficheiro enviado."}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Nenhum ficheiro selecionado."}), 400
    if not pdf_upload.allowed_file(file.filename):
        return jsonify({"error": "Ficheiro inválido."}), 400
    filename = file.filename
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    pdf_upload.pdf_extract(filepath)
    text_lower = pdf_upload.load_txt('pdf/txt/output.txt')
    text = text_lower.lower()
    chunks = pdf_upload.chunk_text(text)
    pdf_upload.make_embeddings(chunks, filename) 
    return redirect(url_for('main'))

@app.route("/ask", methods=["GET"])
def ask():
    user_message = request.args.get("message")
    user_message = user_message.lower()
    if not user_message:
        return "data: Erro: Mensagem inválida.\n\n", 400
    def generate_response():
        try:
            question_embedding = embedding_function([user_message])[0]
            if isinstance(question_embedding, list) and isinstance(question_embedding[0], numpy.ndarray):
                question_embedding = [emb.tolist() if isinstance(emb, numpy.ndarray) else emb for emb in question_embedding]   
            if isinstance(question_embedding, list) and isinstance(question_embedding[0], list):
                question_embedding = question_embedding[0]  # Achar a primeira lista e passar ela
            results = collection.query(
                query_embeddings=[question_embedding],  # Passando a lista de floats diretamente
                n_results=3,
                include=['documents', 'distances', 'embeddings', 'metadatas'],
            )
            if not results or not results["documents"]:
                yield "Nenhuma resposta encontrada para a sua pergunta.\n\n"
                return
            chunks = []
            chunks = [str(document) for document in results['documents']]
            answer_generator = chatbot.pdf_search_answer_stream(chunks, user_message)
            for chunk in answer_generator:
                if chunk.strip():  # Envia a resposta somente se houver conteúdo
                    yield f"data: {chunk}\n\n"
        except Exception as e:
            yield f"Erro interno do servidor: {str(e)}\n\n" 
    return Response(stream_with_context(generate_response()), content_type="text/event-stream")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=15991)
