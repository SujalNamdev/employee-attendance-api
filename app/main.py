"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
from datetime import date
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from decimal import Decimal, ROUND_HALF_UP
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from pymongo import MongoClient
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from fastapi import FastAPI, HTTPException, Query
from bson.json_util import dumps
import json

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

db.attendance_logs.create_index([
    ("date", -1),
    ("emp_code", 1)
])

# //////////////////
print("MongoDB database:", db.name)
print("Employees found:", db.employees.count_documents({}))

IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def compute_late_minutes(punch_in: datetime, shift_start: str) -> int:
    h, m = map(int, shift_start.split(":"))

    start = punch_in.replace(
        hour=h, minute=m, second=0, microsecond=0
    )

    minutes = int((punch_in - start).total_seconds() // 60)

    return minutes if minutes > 10 else 0


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    seconds = (punch_out - punch_in).total_seconds()
    hours = Decimal(str(seconds / 3600)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )
    return float(hours)


def compute_overtime(punch_out: datetime, shift_end: str, date_str: str) -> int:
    h, m = map(int, shift_end.split(":"))

    end = datetime.fromisoformat(date_str).replace(
        hour=h,
        minute=m,
        second=0,
        microsecond=0
    )

    if punch_out <= end:
        return 0

    minutes = int((punch_out - end).total_seconds() // 60)

    return minutes if minutes >= 30 else 0



# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str

class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"

class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None

class AttendanceCorrectionIn(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None



# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    if db.employees.find_one({"emp_code": body.emp_code}):
        raise HTTPException(409, "emp_code already exists")
    doc = body.model_dump()
    doc["created_at"] = datetime.now()
    db.employees.insert_one(doc)
    doc.pop("_id", None)
    return doc


# @app.get("/employees")
# def list_employees(department: Optional[str] = None, page: int = 1, page_size: int = 20):
#     q = {}
#     if department:
#         q["department"] = department
#     skip = (page - 1) * page_size
#     total = db.employees.count_documents(q)
#     print("Employee query:", list(db.employees.find(q, {"_id": 0, "emp_code": 1})))
#     items = list(db.employees.find(q, {"_id": 0}).sort("emp_code", 1).skip(skip).limit(page_size))
#     return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100)
):

    q = {}

    if department:
        q["department"] = department

    skip = (page - 1) * page_size
    total = db.employees.count_documents(q)

    print("Employee query:", list(db.employees.find(q, {"_id": 0, "emp_code": 1})))

    items = list(
        db.employees.find(q, {"_id": 0})
        .sort("emp_code", 1)
        .skip(skip)
        .limit(page_size)
    )

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    # ****************************
    if emp is None:
      raise HTTPException(status_code=404, detail="Employee not found")
    
    ts = (
    datetime.fromtimestamp(body.punched_at / 1000, tz=IST).replace(tzinfo=None)
    if body.punched_at is not None
    else datetime.now(IST).replace(tzinfo=None)
)
    d = ts.date().isoformat()
    if db.attendance_logs.find_one({"emp_code": body.emp_code, "date": d}):
        raise HTTPException(409, "already punched in for this date")
    doc = {
        "emp_code": body.emp_code,
        "date": d,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(ts, emp["shift_start"]),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }
    res = db.attendance_logs.insert_one(doc)
    doc["id"] = str(res.inserted_id)
    doc.pop("_id", None)
    return doc


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    q = {}
    if emp_code:
        q["emp_code"] = emp_code
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    if status:
        q["status"] = status
    total = db.attendance_logs.count_documents(q)

    page_docs = list(
    db.attendance_logs.find(q)
    .sort([("date", -1), ("emp_code", 1)])
    .skip((page - 1) * page_size)
    .limit(page_size)
)
    for d in page_docs:
        d["id"] = str(d.pop("_id"))
    return {"items": page_docs, "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    ts = (
    datetime.fromtimestamp(body.punched_at / 1000, tz=IST).replace(tzinfo=None)
    if body.punched_at is not None
    else datetime.now(IST).replace(tzinfo=None)
)
    record = db.attendance_logs.find_one(
    {
        "emp_code": body.emp_code,
        "punch_in": {
            "$lte": ts,
            "$ne": None
        }
    },
    sort=[("punch_in", -1)]
)

    if record is None:
        raise HTTPException(status_code=404, detail="Punch-in record not found")

    if record["punch_out"] is not None:
        raise HTTPException(status_code=409, detail="Already punched out")

    if ts <= record["punch_in"]:
       raise HTTPException(
        status_code=422,
        detail="Punch-out time must be after punch-in time"
    )

    if ts > record["punch_in"] + timedelta(hours=24):
     raise HTTPException(
        status_code=422,
        detail="Punch-out time cannot be more than 24 hours after punch-in"
    )

    work_hours = compute_work_hours(record["punch_in"], ts)
    overtime_minutes = compute_overtime(
    ts,
    emp["shift_end"],
    record["date"]
)
    half_day = work_hours < 4.50

    db.attendance_logs.update_one(
        {"_id": record["_id"]},
        {
            "$set": {
                "punch_out": ts,
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": half_day
            }
        }
    )

    updated = db.attendance_logs.find_one({"_id": record["_id"]})
    updated["id"] = str(updated.pop("_id"))

    return updated


@app.patch("/attendance/{emp_code}/{date}")
def correct_attendance(
    emp_code: str,
    date: str,
    body: AttendanceCorrectionIn
):
    record = db.attendance_logs.find_one({
        "emp_code": emp_code,
        "date": date
    })

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Attendance record not found"
        )

    changes = {}

    if body.status is not None:
        changes["status"] = body.status

    if body.punch_in is not None:
        changes["punch_in"] = datetime.fromtimestamp(
            body.punch_in / 1000
        )

    if body.punch_out is not None:
        changes["punch_out"] = datetime.fromtimestamp(
            body.punch_out / 1000
        )

    if not changes:
        raise HTTPException(
            status_code=422,
            detail="Provide at least one field to correct"
        )

    history_entry = {
        "changed_at": datetime.now(),
        "changes": {
            key: {
                "old": record.get(key),
                "new": value
            }
            for key, value in changes.items()
        }
    }

    db.attendance_logs.update_one(
        {"_id": record["_id"]},
        {
            "$set": changes,
            "$push": {"history": history_entry}
        }
    )

    updated = db.attendance_logs.find_one({
        "_id": record["_id"]
    })

    updated["id"] = str(updated.pop("_id"))

    return updated

@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly_analytics(
    emp_code: str,
    year: int,
    month: int
):
    if month < 1 or month > 12:
        raise HTTPException(
            status_code=422,
            detail="Month must be between 1 and 12"
        )

    employee = db.employees.find_one({"emp_code": emp_code})

    if employee is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    month_prefix = f"{year:04d}-{month:02d}"

    pipeline = [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {
                    "$regex": f"^{month_prefix}"
                }
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "total_days": {"$sum": 1},
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$status", "PRESENT"]},
                            1,
                            0
                        ]
                    }
                },
                "total_work_hours": {
                    "$sum": {"$ifNull": ["$work_hours", 0]}
                },
                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$late_minutes", 0]}
                },
                "total_overtime_minutes": {
                    "$sum": {"$ifNull": ["$overtime_minutes", 0]}
                }
            }
        }
    ]

    result = list(db.attendance_logs.aggregate(pipeline))

    if not result:
        return {
            "emp_code": emp_code,
            "year": year,
            "month": month,
            "total_days": 0,
            "present_days": 0,
            "total_work_hours": 0,
            "total_late_minutes": 0,
            "total_overtime_minutes": 0
        }

    data = result[0]
    data.pop("_id", None)

    return {
        "emp_code": emp_code,
        "year": year,
        "month": month,
        **data
    }

@app.get("/analytics/departments/summary")
def department_summary():
    pipeline = [
        {
            "$group": {
                "_id": "$department",
                "total_employees": {"$sum": 1}
            }
        }
    ]

    departments = list(db.employees.aggregate(pipeline))

    return {
        "departments": [
            {
                "department": item["_id"],
                "total_employees": item["total_employees"]
            }
            for item in departments
        ]
    }


@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str,
    limit: int = Query(default=10, ge=1, le=50),
    department: Optional[str] = None
):
    import re

    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(
            status_code=422,
            detail="Month must be in YYYY-MM format"
        )

    pipeline = [
        {
            "$match": {
                "date": {"$regex": f"^{month}"},
                "late_minutes": {"$gt": 0}
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"},
                "late_count": {"$sum": 1}
            }
        },
        {
            "$sort": {
                "total_late_minutes": -1,
                "_id": 1
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee"
            }
        },
        {"$unwind": "$employee"}
    ]

    if department:
        pipeline.append({
            "$match": {"employee.department": department}
        })

    pipeline.extend([
        {
    "$setWindowFields": {
        "sortBy": {
            "total_late_minutes": -1
        },
        "output": {
            "rank": {"$rank": {}}
        }
    }
},
        {"$match": {"rank": {"$lte": limit}}},
        {
            "$project": {
                "_id": 0,
                "rank": 1,
                "emp_code": "$_id",
                "name": "$employee.name",
                "department": "$employee.department",
                "total_late_minutes": 1,
                "late_count": 1
            }
        },
        {
            "$sort": {
                "total_late_minutes": -1,
                "emp_code": 1
            }
        }
    ])

    items = list(db.attendance_logs.aggregate(pipeline))

    return {
        "month": month,
        "items": items
    }

@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to")
):
    if to_date < from_date:
        raise HTTPException(
            status_code=422,
            detail="'to' must be on or after 'from'"
        )

    if (to_date - from_date).days + 1 > 92:
        raise HTTPException(
            status_code=422,
            detail="Date range cannot exceed 92 days"
        )

    # Check that the department exists
    employee_count = db.employees.count_documents(
        {"department": department}
    )

    if employee_count == 0:
        raise HTTPException(
            status_code=404,
            detail="Department not found"
        )

    start_date = from_date.isoformat()
    end_date = to_date.isoformat()

    pipeline = [
        {
            "$match": {
                "department": department,
                "joined_on": {"$lte": end_date}
            }
        },
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"employee_code": "$emp_code"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {
                                        "$eq": [
                                            "$emp_code",
                                            "$$employee_code"
                                        ]
                                    },
                                    {"$gte": ["$date", start_date]},
                                    {"$lte": ["$date", end_date]}
                                ]
                            }
                        }
                    }
                ],
                "as": "logs"
            }
        },
        {"$unwind": "$logs"},
        {
            "$group": {
                "_id": "$logs.date",
                "present_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$logs.status", "PRESENT"]},
                            {
                                "$cond": [
                                    {"$eq": ["$logs.half_day", True]},
                                    0.5,
                                    1
                                ]
                            },
                            0
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$logs.late_minutes", 0]},
                            1,
                            0
                        ]
                    }
                }
            }
        },
        {"$sort": {"_id": 1}}
    ]

    daily_results = list(db.employees.aggregate(pipeline))
    daily_lookup = {item["_id"]: item for item in daily_results}

    # Build one output row for every calendar day
    items = []
    current_date = from_date

    while current_date <= to_date:
        day = current_date.isoformat()
        is_working_day = current_date.weekday() < 5

        headcount = db.employees.count_documents({
            "department": department,
            "joined_on": {"$lte": day}
        })

        daily = daily_lookup.get(day, {})
        present_count = daily.get("present_count", 0)
        late_count = daily.get("late_count", 0)

        if is_working_day and headcount > 0:
            attendance_rate = round(present_count / headcount, 4)
        else:
            attendance_rate = None

        items.append({
            "date": day,
            "is_working_day": is_working_day,
            "headcount": headcount,
            "present_count": present_count,
            "late_count": late_count,
            "attendance_rate": attendance_rate
        })

        current_date += timedelta(days=1)

    # Calculate moving average from the available non-null rates
    for index, item in enumerate(items):
        window = items[max(0, index - 6):index + 1]
        rates = [
            row["attendance_rate"]
            for row in window
            if row["attendance_rate"] is not None
        ]

        item["moving_avg_7d"] = (
            round(sum(rates) / len(rates), 4)
            if rates else None
        )

    return {
        "department": department,
        "from": start_date,
        "to": end_date,
        "items": items
    }

@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: str,
    month: Optional[str] = None,
    department: Optional[str] = None,
    emp_code: Optional[str] = None,
    from_date: Optional[date] = Query(default=None, alias="from"),
    to_date: Optional[date] = Query(default=None, alias="to"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    limit: int = Query(default=10, ge=1, le=50)
):
    allowed_endpoints = {
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend"
    }

    if endpoint not in allowed_endpoints:
        raise HTTPException(
            status_code=422,
            detail="Unsupported endpoint name"
        )

    if endpoint == "attendance_list":
        query = {}
        if emp_code:
            query["emp_code"] = emp_code
        if department:
            employee_codes = db.employees.distinct(
                "emp_code",
                {"department": department}
            )
            query["emp_code"] = {"$in": employee_codes}

        result = db.command(
    "explain",
    {
        "find": "attendance_logs",
        "filter": query,
        "sort": {"date": -1, "emp_code": 1},
        "skip": (page - 1) * page_size,
        "limit": page_size
    },
    verbosity="executionStats"
)

    elif endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(
                status_code=422,
                detail="emp_code and month are required"
            )

        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise HTTPException(
                status_code=422,
                detail="month must use YYYY-MM format"
            )

        pipeline = [
            {
                "$match": {
                    "emp_code": emp_code,
                    "date": {
                        "$gte": f"{month}-01",
                        "$lt": (
                            f"{int(month[:4]) + (int(month[5:7]) == 12):04d}-"
                            f"{1 if int(month[5:7]) == 12 else int(month[5:7]) + 1:02d}-01"
                        )
                    }
                }
            },
            {
                "$group": {
                    "_id": "$emp_code",
                    "total_late_minutes": {
                        "$sum": {"$ifNull": ["$late_minutes", 0]}
                    }
                }
            }
        ]

        result = db.attendance_logs.aggregate(pipeline).explain(
            verbosity="executionStats"
        )

    elif endpoint == "department_summary":
        if not month:
            raise HTTPException(
                status_code=422,
                detail="month is required"
            )

        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise HTTPException(
                status_code=422,
                detail="month must use YYYY-MM format"
            )

        pipeline = [
            {
                "$match": {
                    "date": {
                        "$gte": f"{month}-01",
                        "$lt": (
                            f"{int(month[:4]) + (int(month[5:7]) == 12):04d}-"
                            f"{1 if int(month[5:7]) == 12 else int(month[5:7]) + 1:02d}-01"
                        )
                    }
                }
            },
            {
                "$group": {
                    "_id": "$department",
                    "records": {"$sum": 1}
                }
            }
        ]

        result = db.attendance_logs.aggregate(pipeline).explain(
            verbosity="executionStats"
        )

    elif endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(
                status_code=422,
                detail="month is required"
            )

        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise HTTPException(
                status_code=422,
                detail="month must use YYYY-MM format"
            )

        pipeline = [
            {
                "$match": {
                    "date": {
                        "$gte": f"{month}-01",
                        "$lt": (
                            f"{int(month[:4]) + (int(month[5:7]) == 12):04d}-"
                            f"{1 if int(month[5:7]) == 12 else int(month[5:7]) + 1:02d}-01"
                        ),
                    },
                    "late_minutes": {"$gt": 0}
                }
            },
            {
                "$group": {
                    "_id": "$emp_code",
                    "total_late_minutes": {"$sum": "$late_minutes"}
                }
            },
            {"$sort": {"total_late_minutes": -1, "_id": 1}},
            {"$limit": limit}
        ]

        result = db.attendance_logs.aggregate(pipeline).explain(
            verbosity="executionStats"
        )

    else:
        if not department or not from_date or not to_date:
            raise HTTPException(
                status_code=422,
                detail="department, from and to are required"
            )

        if to_date < from_date:
            raise HTTPException(
                status_code=422,
                detail="'to' must be on or after 'from'"
            )

        if (to_date - from_date).days + 1 > 92:
            raise HTTPException(
                status_code=422,
                detail="Date range cannot exceed 92 days"
            )

        pipeline = [
            {
                "$match": {
                    "department": department,
                    "date": {
                        "$gte": from_date.isoformat(),
                        "$lte": to_date.isoformat()
                    }
                }
            },
            {"$sort": {"date": 1}}
        ]

        result = db.attendance_logs.aggregate(pipeline).explain(
            verbosity="executionStats"
        )

    return json.loads(dumps(result))

# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #
