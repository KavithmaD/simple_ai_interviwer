from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
import fitz 
from motor.motor_asyncio import AsyncIOMotorClient
import google.generativeai as genai
from bson import ObjectId
import json
import random
from dotenv import load_dotenv
import os

load_dotenv()

app = FastAPI()

genai.configure(api_key=os.getenv("GENAI_API_KEY"))

MONGO_URL = os.getenv("MONGO_URL")
client = AsyncIOMotorClient(MONGO_URL)
db = client["ai_hiring"]
resume_collection = db.get_collection("resumes")


# Allow requests from your frontend
origins = [
    "http://localhost:3001",  # Add your React app's origin
    "http://localhost:3000",  # If using another port
    "https://your-frontend-domain.com",  # Add production frontend URL
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Allows only specified origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allows all headers
)


@app.get("/")
def home():
   return {"message": "AI Hiring Platform Backend is Running!"}
  
@app.post("/upload-resume/")
async def upload_resume(file: UploadFile = File(...), fid: str = Form(...)):
    """
    Upload a resume (PDF), extract text, store it in MongoDB.
    """
    try:
        content = await file.read()
        doc = fitz.open(stream=content, filetype="pdf")
        text = "\n".join([page.get_text() for page in doc])
        extracted_info = await extract_resume_info(text)

        resume_data = {
            "filename": file.filename,
            "text": extracted_info,
            "fid": fid
        }

        # Insert into MongoDB
        result = await resume_collection.insert_one(resume_data)
        return {"message": "Resume stored successfully", "id": str(result.inserted_id)}

    except Exception as e:
        return {"error": str(e)}

@app.get("/get-resume/{fid}")
async def get_resume(fid: str):
    """
    Retrieve a resume from MongoDB by its ID.
    """
    try:
        
        # obj_id = ObjectId(resume_id) 
        resume = await resume_collection.find_one({"fid": fid})
        if not resume:
            return {"error": "Resume not found"}
        
        resume["_id"] = str(resume["_id"])
        return {"resume": resume}

    except Exception as e:
        return {"error": str(e)}

async def extract_resume_info(text: str):
    """
    Extracts key details (name, skills, projects, experience, education) from resume text using Gemini API.
    """
    prompt = f"""
    Extract the following key details from the resume text:
    - Name
    - Skills
    - Projects
    - Experience
    - Education
    - Other important details

    Resume text:
    {text}

    Provide the output in **valid JSON format** without any additional text.
    """

    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content(prompt)

    # Print raw response for debugging
    print("🔹 Raw Response from Gemini:", response.text)

    # Remove triple backticks if present
    cleaned_response = response.text.strip().strip("```json").strip("```")

    try:
        extracted_info = json.loads(cleaned_response)
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON response from Gemini: {str(e)}", "raw_response": cleaned_response}

    return extracted_info


@app.get("/extract-info/{resume_id}")
async def extract_info(resume_id: str):
    """
    Fetches resume text from MongoDB and extracts key details using Gemini API.
    """
    try:
        obj_id = ObjectId(resume_id)
        resume = await resume_collection.find_one({"_id": obj_id})
        if not resume:
            return {"error": "Resume not found"}

        resume["_id"] = str(resume["_id"])
        extracted_info = await extract_resume_info(resume["text"])
        
        return {"extracted_info": extracted_info}

    except Exception as e:
        return {"error": str(e)}





async def generate_mcqs(skills):
    """
    Randomly picks 12 skills and generates 5 MCQs for Easy, Medium, and Hard levels.
    """
    if len(skills) < 12:
        return {"error": "Not enough skills available to generate MCQs"}

    # Randomly select 12 skills: 4 for each difficulty level
    selected_skills = random.sample(skills, 12)
    easy_skills = selected_skills[:4]
    medium_skills = selected_skills[4:8]
    hard_skills = selected_skills[8:]

    prompt = f"""
    Generate multiple-choice questions (MCQs) based on the following skills:

    - **Easy Skills**: {', '.join(easy_skills)}
    - **Medium Skills**: {', '.join(medium_skills)}
    - **Hard Skills**: {', '.join(hard_skills)}

    **Instructions:**
    - Generate **5 MCQs per difficulty level**.
    - Each question should have **4 options**, with one correct answer.
    - The generated questions must be directly related to the skill.
    - Include the skill name in the question or answer choices.
    - Make sure the questions are unique, clear, and well-structured.
    - The incorrect options should be plausible but clearly incorrect to someone familiar with the skill.
    - **Output must be in JSON format**:

    ```json
    {{
      "easy": [
        {{"question": "Q1", "options": ["A", "B", "C", "D"], "answer": "A", "skill": "Skill1"}},
        ...
      ],
      "medium": [
        {{"question": "Q1", "options": ["A", "B", "C", "D"], "answer": "B", "skill": "Skill5"}},
        ...
      ],
      "hard": [
        {{"question": "Q1", "options": ["A", "B", "C", "D"], "answer": "C", "skill": "Skill9"}},
        ...
      ]
    }}
    ```

    Return only valid JSON without explanations or formatting errors.
    """

    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content(prompt)

    # Clean response and parse JSON
    cleaned_response = response.text.strip().strip("```json").strip("```")

    try:
        mcq_data = json.loads(cleaned_response)
        return mcq_data
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON from Gemini: {str(e)}", "raw_response": cleaned_response}
    
    
    
    
@app.get("/generate-mcqs/{fid}")
async def generate_resume_mcqs(fid: str):
    """
    Fetch skills from MongoDB and generate MCQs.
    """
   

    # obj_id = ObjectId(resume_id)
    resume = await resume_collection.find_one({"fid": fid})

    if not resume:
        return {"error": "Resume not found"}

    skills = resume.get("text", {}).get("Skills", [])

    if not skills:
        return {"error": "No skills found in resume"}

    mcqs = await generate_mcqs(skills)

    return {"mcqs": mcqs}




# Function to generate interview questions
async def generate_question(projects, experience, name, candidate_response=None):
    """
    Generates an interview question based on projects, experience, and candidate's last response.
    """
    context = ""

    if candidate_response:
        context += f"\nCandidate Response: {candidate_response}\n"

    prompt = f"""
    You are an expert interviewer who is conducting a chat with a candidate for a software engineering position. Your task is to ask the candidate questions to evaluate their skills and experience.
    Every chat must start with greetings and friendly chat with the candidate. If data contains personal information like {name} make sure to use it for greeting the candidate and other personalizations. One key thing is manage pace of the conversation and ask questions in a way that it feels like a real conversation. first start from greeting and then ask about their work experience.
    - The candidate has experience in {', '.join(experience) if experience else 'various fields'}.
    - Their projects include {', '.join(projects) if projects else 'various technologies'}.
    - Ask short but meaningful technical questions (max 2 sentences).
    - Ensure questions are conversational and follow up on the candidate's answers.
    - If the candidate says "exit", return: {{"message": "Interview ended."}}
    
    Context:
    {context}
    
    Generate the next question in JSON format:
    ```json
    {{
      "question": "Your next question here"
    }}
    ```
    """

    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content(prompt)

    # Parse response
    cleaned_response = response.text.strip().strip("```json").strip("```")

    try:
        question_data = json.loads(cleaned_response)
        return question_data
    except json.JSONDecodeError:
        return {"error": "Invalid JSON from Gemini"}
    
    

@app.post("/interview/{fid}")
async def interview(fid: str, candidate_response: str = None):
    """
    Conducts an AI interview based on the candidate's resume.
    """
   
    resume = await resume_collection.find_one({"fid": fid})

    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    projects = resume.get("text", {}).get("Projects", [])
    experience = resume.get("text", {}).get("Experience", [])
    name = resume.get("text", {}).get("Name", [])
    
    # Convert dictionaries to strings if needed
    experience = [exp if isinstance(exp, str) else json.dumps(exp) for exp in experience]
    projects = [pro if isinstance(pro, str) else json.dumps(pro) for pro in projects]

    if candidate_response and candidate_response.lower() == "exit":
        return {"message": "Interview ended."}

    # Generate next question
    question = await generate_question(projects, experience, name, candidate_response)
    return question

@app.get("/get-all-resumes")
async def get_all_resumes():
    """
    Retrieve all resumes from MongoDB.
    """
    try:
        resumes = await resume_collection.find().to_list(None)  # Convert cursor to list
        for resume in resumes:
            resume["_id"] = str(resume["_id"])  # Convert ObjectId to string
        
        return {"resumes": resumes}

    except Exception as e:
        return {"error": str(e)}
