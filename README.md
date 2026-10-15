# Employee Attendance & Analytics API

A REST API built with Python, FastAPI, and MongoDB for employee management, attendance tracking, manual attendance corrections, and attendance analytics.

## Features

- Create and list employee records.
- Record employee punch-in and punch-out.
- Calculate attendance values according to business rules.
- List attendance records with pagination and filtering.
- Correct attendance records with an audit trail.
- Generate employee and department analytics.
- Rank employees by late minutes.
- Generate department attendance trends.
- Inspect MongoDB query plans using explain functionality.

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

The exact files included may vary according to the supplied candidate kit.

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

Configure the following environment variables:

```env
MONGO_URI=your_mongodb_connection_string
MONGO_DB=attendance_db
```

Replace `your_mongodb_connection_string` with your actual MongoDB connection string.

Keep `.env` private. Do not commit database credentials or other secrets to GitHub.

## Seed Data

If the supplied seed script is available, run:

```bash
python sample_seed.py
```

Use the provided sample data and follow the assignment instructions for loading it into MongoDB.

## Run the API

From the project root directory, run:

```bash
python -m uvicorn app.main:app --port 8000
```

The local API address is:

```text
http://127.0.0.1:8000
```

## API Documentation

When the server is running, open:

- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

Use Swagger UI to inspect and test the available endpoints.

## Main API Areas

### Employee Management

Create and retrieve employee records.

### Attendance Management

Record punch-in and punch-out events, retrieve attendance records, and apply manual corrections.

### Analytics

Retrieve employee monthly analytics, department summaries, late-arrival rankings, and department attendance trends.

### Query Plan Inspection

Inspect MongoDB execution plans and statistics through the admin explain endpoint.

## Database Design

The application uses two primary collections:

- `employees`
- `attendance_logs`

The `attendance_logs` collection identifies a record using an employee code and an attendance date. Database indexes should support the API's query patterns and duplicate-prevention requirements.

## Documentation

- `REVIEW.md` describes code-review findings and recommendations.
- `DECISIONS.md` explains the main design choices and trade-offs.

## Security Notes

- Never commit `.env` or database credentials.
- Avoid exposing database connection strings in logs or error responses.
- Configure MongoDB network access and database permissions appropriately.

## Testing

Run the API and test its endpoints through Swagger UI. Validate successful operations, invalid inputs, duplicate attendance attempts, manual correction history, analytics calculations, and MongoDB query plans.

The implementation should be checked against the supplied OpenAPI contract and business rules before submission.
