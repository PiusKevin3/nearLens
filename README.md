
# NearLens

NearLens is a visual local discovery application. Users can upload or take a photo, identify objects in it, and find nearby relevant places using the Google Places API.

This repository contains both the **backend** (Python / Google ADK) and the **frontend client** (Next.js).

---

## Table of Contents

* [Project Structure](#project-structure)
* [Prerequisites](#prerequisites)
* [Backend Setup](#backend-setup)
* [Client Setup](#client-setup)
* [Environment Variables](#environment-variables)
* [Running the Project](#running-the-project)
* [Technologies Used](#technologies-used)

---

## Project Structure

```
nearLens/
├─ backend/
│  ├─ nearLens_agent/
│  │  ├─ agent.py
│  │  ├─ tools/
│  │  │  ├─ instructions.py
│  │  │  ├─ type_mapping.py
│  │  │  └─ places_mapping.py
│  │  └─ ...other modules
│  └─ requirements.txt
├─ client/
│  ├─ pages/
│  ├─ components/
│  ├─ public/
│  └─ package.json
└─ README.md
```

---

## Prerequisites

### Backend

* Python 3.10+
* `pip` package manager
* `.env` file with API keys

### Client

* Node.js 18+
* npm or yarn
* Next.js (installed via package.json)

---

## Backend Setup

1. Navigate to the backend folder:

```bash
cd backend
```

2. Create and activate a virtual environment:

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Configure environment variables:

Create a `.env` file in the backend folder:

```
GOOGLE_GENAI_MODEL=gemini-2.5-flash
GOOGLE_PLACES_API_KEY=your_google_places_api_key
```

5. Run the backend API:

```bash
uvicorn main:app --reload
```

---

## Client Setup (Next.js)

1. Navigate to the client folder:

```bash
cd client
```

2. Install dependencies:

```bash
npm install
# or
yarn install
```

3. Configure environment variables:

Create a `.env.local` file in the client folder:

```
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000   # or your deployed backend
```

4. Run the development server:

```bash
npm run dev
# or
yarn dev
```

5. Open your browser at [http://localhost:3000](http://localhost:3000)

---

## Environment Variables

### Backend

* `GOOGLE_GENAI_MODEL` — Model name for Google ADK agents (default: `gemini-2.5-flash`)
* `GOOGLE_PLACES_API_KEY` — Google Places API key

### Frontend (Next.js)

* `NEXT_PUBLIC_BACKEND_URL` — URL for the backend API

---

## Running the Project

1. Start the backend:

```bash
cd backend
source venv/bin/activate  # activate virtual environment
uvicorn main:app --reload
```

2. Start the frontend:

```bash
cd client
npm run dev
```

3. Open the app in a browser at [http://localhost:3000](http://localhost:3000) and test image uploads and location-based searches.

---

## Technologies Used

* **Backend:** Python, Google ADK, Pydantic, Requests, dotenv
* **Frontend:** Next.js, React, Tailwind CSS (optional)
* **APIs:** Google Places API (New), Google GenAI Models


