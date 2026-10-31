# Employee Attendance & Analytics API

A REST API built with Python, FastAPI, and MongoDB for employee management, attendance tracking, manual attendance corrections, and attendance analytics.

## Features

- Create and list employee records.
- Record employee punch-in and punch-out events.
- Calculate attendance metrics according to defined business rules.
- Retrieve attendance records with filtering and pagination.
- Correct attendance records with an audit trail.
- Generate employee monthly analytics.
- Generate department summaries and attendance trends.
- Rank employees by total late minutes.
- Inspect MongoDB query execution plans using the explain functionality.

## Technology Stack

- Python
- FastAPI
- MongoDB
- PyMongo
- Pydantic
- Uvicorn

## Project Structure

```text
candidate_kit/
├── app/
│   └── main.py
├── requirements.txt
├── README.md
├── REVIEW.md
├── DECISIONS.md
├── sample_data/
└── sample_seed.py
```

## Prerequisites

- Python installed on your computer.
- A MongoDB Atlas cluster or another accessible MongoDB instance.
- The project dependencies installed from `requirements.txt`.

## Installation

Open a terminal in the project root directory and install the dependencies:

```bash
python -m pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project root directory.

Add the following environment variables:

```env
MONGO_URI=your_mongodb_connection_string
MONGO_DB=attendance_db
```

Replace `your_mongodb_connection_string` with your actual MongoDB connection string.

Keep the `.env` file private. Never commit database credentials or other secrets to GitHub.

## Seed Data

The project includes a sample seed script for loading sample employees and attendance records.

To load the sample data, run the following command from the project root directory:

```bash
python sample_seed.py
```

Run the seed script when setting up the database with the provided sample data. Avoid running it repeatedly unless the script is designed to handle repeated execution safely.

## Running the API

From the project root directory, start the application using:

```bash
python -m uvicorn app.main:app --port 8000
```

The API will be available at:

```text
http://127.0.0.1:8000
```

## API Documentation

When the server is running, access the following documentation:

- **Swagger UI:** http://127.0.0.1:8000/docs
- **OpenAPI JSON:** http://127.0.0.1:8000/openapi.json

Swagger UI can be used to explore the available endpoints and inspect their request and response schemas.

## Main API Areas

### Employee Management

Create and retrieve employee records.

### Attendance Management

Record punch-in and punch-out events, retrieve attendance records, and apply manual corrections with an audit trail.

### Analytics

Retrieve employee monthly analytics, department summaries, late-arrival rankings, and department attendance trends.

### Query Plan Inspection

Inspect MongoDB query execution plans and execution statistics through the admin explain endpoint.

## Database Design

The application uses two primary MongoDB collections:

- `employees`
- `attendance_logs`

The `attendance_logs` collection stores employee attendance records identified by employee code and attendance date.

Database indexes support common query patterns and help enforce duplicate-prevention requirements.

## Documentation

- `REVIEW.md` contains code-review findings and recommendations.
- `DECISIONS.md` explains the main design choices and trade-offs.

## Security Notes

- Never commit `.env` files or database credentials.
- Avoid exposing database connection strings in logs or error responses.
- Configure MongoDB network access and database permissions appropriately.

## Verification

The API was checked through Swagger UI and local endpoint execution. Verification covered employee management, attendance operations, business-rule calculations, manual corrections and audit history, analytics endpoints, and MongoDB query execution plans.

The implementation should remain consistent with the supplied OpenAPI contract and business rules.
