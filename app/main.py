"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
import re
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Literal, Annotated

from bson.json_util import dumps
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"),tz_aware=True)
db = client[os.getenv("MONGO_DB", "attendance_db")]


def create_indexes():
    # An employee code must be unique.
    db.employees.create_index(
        [("emp_code", 1)],
        unique=True,
        name="uq_employee_emp_code",
    )
    db.employees.create_index(
        [
            ("department", 1),
            ("joined_on", 1),
            ("emp_code", 1)
        ],
        name="idx_employees_department_joined_emp"
    )
    db.employees.create_index(
    [("department", 1)],
    name="idx_employees_department"
    )

    # One attendance record per employee per attendance date.
    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", 1)],
        unique=True,
        name="uq_attendance_emp_date",
    )

    # Supports attendance listing by date and employee code.
    db.attendance_logs.create_index(
    [("date", -1), ("emp_code", 1)],
    )


create_indexes()


IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def truncate_to_seconds(ts: datetime) -> datetime:
    """Remove microseconds before calculations and storage."""
    return ts.replace(microsecond=0)


def get_attendance_date(
    punch_in: datetime,
    shift_start: str,
    shift_end: str
) -> str:
    """Return the attendance date in IST, accounting for overnight shifts."""
    local_punch_in = punch_in.astimezone(IST)
    attendance_date = local_punch_in.date()

    start_time = datetime.strptime(shift_start, "%H:%M").time()
    end_time = datetime.strptime(shift_end, "%H:%M").time()
    punch_time = local_punch_in.time().replace(tzinfo=None)

    # A shift is overnight when it ends at or before it starts.
    if end_time <= start_time and punch_time < end_time:
        attendance_date -= timedelta(days=1)

    return attendance_date.isoformat()


def compute_late_minutes(
    punch_in: datetime,
    shift_start: str,
    shift_end: str
) -> int:
    punch_in_ist = punch_in.astimezone(IST).replace(microsecond=0)

    start_hour, start_minute = map(int, shift_start.split(":"))

    shift_start_dt = punch_in_ist.replace(
        hour=start_hour,
        minute=start_minute,
        second=0,
        microsecond=0
    )

    start_time = datetime.strptime(shift_start, "%H:%M").time()
    end_time = datetime.strptime(shift_end, "%H:%M").time()
    punch_time = punch_in_ist.time().replace(tzinfo=None)

    # Early-morning punches for overnight shifts belong to
    # the shift that started on the previous day.
    if end_time <= start_time and punch_time < end_time:
        shift_start_dt -= timedelta(days=1)

    delay_seconds = (punch_in_ist - shift_start_dt).total_seconds()

    # A delay of exactly 10 minutes is not late.
    if delay_seconds <= 10 * 60:
        return 0

    # Count whole elapsed minutes since shift start.
    return int(delay_seconds // 60)



def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    punch_in = punch_in.replace(microsecond=0)
    punch_out = punch_out.replace(microsecond=0)

    elapsed_seconds = int((punch_out - punch_in).total_seconds())
    hours = Decimal(elapsed_seconds) / Decimal(3600)

    rounded_hours = hours.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )

    return float(rounded_hours)


def round_half_up(value: float, places: int = 4) -> float:
    return float(
        Decimal(str(value)).quantize(
            Decimal("1." + "0" * places),
            rounding=ROUND_HALF_UP
        )
    )


def compute_overtime(
        
    punch_out: datetime,
    shift_start: str,
    shift_end: str,
    date_str: str
) -> int:
    # Use the attendance date and the employee's shift times in IST.
    attendance_date = datetime.fromisoformat(date_str).replace(tzinfo=IST)

    start_hour, start_minute = map(int, shift_start.split(":"))
    end_hour, end_minute = map(int, shift_end.split(":"))

    shift_start_dt = attendance_date.replace(
        hour=start_hour,
        minute=start_minute,
        second=0,
        microsecond=0
    )

    shift_end_dt = attendance_date.replace(
        hour=end_hour,
        minute=end_minute,
        second=0,
        microsecond=0
    )

    # If the shift ends at or before it starts, it runs overnight.
    if shift_end_dt <= shift_start_dt:
        shift_end_dt += timedelta(days=1)

    # Compare both timestamps in UTC.
    punch_out = punch_out.astimezone(timezone.utc).replace(microsecond=0)
    shift_end_utc = shift_end_dt.astimezone(timezone.utc)

    if punch_out <= shift_end_utc:
        return 0

    # Count whole elapsed minutes after the shift ends.
    overtime_minutes = int(
        (punch_out - shift_end_utc).total_seconds() // 60
    )

    # Overtime is counted only when it reaches at least 30 minutes.
    return overtime_minutes if overtime_minutes >= 30 else 0



EpochMillis = Annotated[
    StrictInt,
    Field(ge=100_000_000_000, le=4_102_444_800_000),
]


def datetime_from_epoch_ms(value: int) -> datetime:
    """Convert validated epoch milliseconds to a UTC-aware datetime."""
    try:
        result = datetime.fromtimestamp(
            value / 1000,
            tz=timezone.utc,
        )
    except (ValueError, OverflowError, OSError):
        raise HTTPException(
            status_code=422,
            detail="Invalid timestamp",
        )

    return result.replace(microsecond=0)


def epoch_ms(value: Optional[datetime]) -> Optional[int]:
    """Convert a stored BSON datetime to epoch milliseconds."""
    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    value = value.astimezone(timezone.utc).replace(microsecond=0)
    return int(value.timestamp() * 1000)


def attendance_response(doc: dict) -> dict:
    return {
        "emp_code": doc["emp_code"],
        "date": doc["date"],
        "status": doc["status"],
        "punch_in": epoch_ms(doc.get("punch_in")),
        "punch_out": epoch_ms(doc.get("punch_out")),
        "work_hours": doc.get("work_hours"),
        "late_minutes": doc.get("late_minutes", 0),
        "overtime_minutes": doc.get("overtime_minutes", 0),
        "half_day": doc.get("half_day", False),
        "history": [
            {
                "at": epoch_ms(entry.get("at")),
                "by": entry.get("by", ""),
                "reason": entry.get("reason", ""),
                "changes": {
                    key: {
                        "from": (
                        epoch_ms(change["from"])
                        if key in ("punch_in", "punch_out") and "from" in change
                        else change.get("from")
                       ),
                       "to": (
                       epoch_ms(change["to"])
                       if key in ("punch_in", "punch_out") and "to" in change
                       else change.get("to")
                   ),
                    }
                    for key, change in entry["changes"].items()
                },
            }
            for entry in doc.get("history", [])
        ],
    }

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
    joined_on: date

    @model_validator(mode="after")
    def validate_shift(self):
        if self.shift_start == self.shift_end:
            raise ValueError("shift_start and shift_end must be different")
        return self


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[EpochMillis] = None
    status: Literal["PRESENT", "WFH", "ON_DUTY"] = "PRESENT"


class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[EpochMillis] = None


class AttendanceCorrectionIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Optional[
        Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]
    ] = None
    punch_in: Optional[EpochMillis] = None
    punch_out: Optional[EpochMillis] = None
    reason: str = Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)


# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    try:
        db.command("ping")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable"
        )


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):

    if db.employees.find_one({"emp_code": body.emp_code}):
        raise HTTPException(409, "emp_code already exists")

    doc = body.model_dump()

    doc["joined_on"] = body.joined_on.isoformat()

    doc["created_at"] = datetime.now()

    db.employees.insert_one(doc)

    doc.pop("_id", None)

    return doc


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

    if emp is None:
      raise HTTPException(status_code=404, detail="Employee not found")
    
    try:
     ts = (
    datetime_from_epoch_ms(body.punched_at)
    if body.punched_at is not None
    else datetime.now(timezone.utc).replace(microsecond=0)
)
    except (ValueError, OverflowError, OSError):
     raise HTTPException(
        status_code=422,
        detail="Invalid punch-in timestamp"
    )

    # d = ts.date().isoformat()
    ts = truncate_to_seconds(ts)
    d = get_attendance_date(ts, emp["shift_start"], emp["shift_end"])
    if db.attendance_logs.find_one({"emp_code": body.emp_code, "date": d}):
        raise HTTPException(409, "already punched in for this date")
    doc = {
        "emp_code": body.emp_code,
        "date": d,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes" : compute_late_minutes(
        ts,
        emp["shift_start"],
        emp["shift_end"]
         ),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }
    try:
     db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
      raise HTTPException(
        status_code=409,
        detail="already punched in for this date",
    )

    return attendance_response(doc)


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status: Optional[Literal["PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"]] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):

    q = {}

    if emp_code:
        q["emp_code"] = emp_code

    if date_from or date_to:
        q["date"] = {}
        if date_from:
         q["date"]["$gte"] = date_from.isoformat()
        if date_to:
         q["date"]["$lte"] = date_to.isoformat()

    if status:
        q["status"] = status

    total = db.attendance_logs.count_documents(q)

    page_docs = list(
        db.attendance_logs.find(q)
        .sort([("date", -1), ("emp_code", 1)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )

    items = [attendance_response(doc) for doc in page_docs]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }



@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if emp is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    ts = (
        datetime_from_epoch_ms(body.punched_at)
        if body.punched_at is not None
        else datetime.now(timezone.utc).replace(microsecond=0)
    )
    ts = truncate_to_seconds(ts)
    record_date = get_attendance_date(
    ts,
    emp["shift_start"],
    emp["shift_end"],
    )

    record = db.attendance_logs.find_one(
    {
        "emp_code": body.emp_code,
        "date": record_date,
        "punch_in": {"$ne": None, "$lte": ts},
        "punch_out": None,
    }
)

    if record is None:
        previous = db.attendance_logs.find_one(
        {
        "emp_code": body.emp_code,
        "date": record_date,
        "punch_in": {"$ne": None},
        "punch_out": {"$ne": None},
         }
         )

        if previous is not None:
            raise HTTPException(
                status_code=409,
                detail="Already punched out",
            )

        raise HTTPException(
            status_code=404,
            detail="Punch-in record not found",
        )

    if ts <= record["punch_in"]:
        raise HTTPException(
            status_code=422,
            detail="Punch-out time must be after punch-in time",
        )

    if ts > record["punch_in"] + timedelta(hours=24):
        raise HTTPException(
            status_code=422,
            detail="Punch-out time cannot be more than 24 hours after punch-in",
        )

    work_hours = compute_work_hours(record["punch_in"], ts)

    overtime_minutes = compute_overtime(
        ts,
        emp["shift_start"],
        emp["shift_end"],
        record["date"],
    )

    half_day = work_hours < 4.50

    result = db.attendance_logs.update_one(
        {
            "_id": record["_id"],
            "punch_out": None,
        },
        {
            "$set": {
                "punch_out": ts,
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": half_day,
            }
        },
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Already punched out",
        )

    updated = db.attendance_logs.find_one(
        {"_id": record["_id"]}
    )

    return attendance_response(updated)


@app.patch("/attendance/{emp_code}/{date}")
def correct_attendance(
    emp_code: str,
    date: str,
    body: AttendanceCorrectionIn,
):
    record = db.attendance_logs.find_one(
        {
            "emp_code": emp_code,
            "date": date,
        }
    )

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Attendance record not found",
        )

    emp = db.employees.find_one({"emp_code": emp_code})

    if emp is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    supplied_fields = body.model_fields_set
    changes = {}

    # Include only explicitly supplied fields that actually change.
    if "status" in supplied_fields:
        if record.get("status") != body.status:
            changes["status"] = body.status

    for field in ("punch_in", "punch_out"):
        if field in supplied_fields:
            value = (
                datetime_from_epoch_ms(getattr(body, field))
                if getattr(body, field) is not None
                else None
            )

            if value is not None:
                value = truncate_to_seconds(value)

            if record.get(field) != value:
                changes[field] = value

    if not changes:
        raise HTTPException(
            status_code=422,
            detail="No attendance fields changed",
        )

    corrected = {**record, **changes}
    status = corrected["status"]
    punch_in = corrected.get("punch_in")
    punch_out = corrected.get("punch_out")

    # ABSENT and LEAVE records cannot have punch timestamps.
    if status in ("ABSENT", "LEAVE"):
        if punch_in is not None or punch_out is not None:
            raise HTTPException(
                status_code=422,
                detail="ABSENT and LEAVE records must have null punch times",
            )
        if status in ("PRESENT", "WFH", "ON_DUTY") and punch_in is None:
         raise HTTPException(
        status_code=422,
        detail="Punch-in is required for PRESENT, WFH, and ON_DUTY records",
    )

    # Records with punch-out must have a punch-in.
    if punch_out is not None and punch_in is None:
        raise HTTPException(
            status_code=422,
            detail="Punch-in is required before punch-out",
        )

    if punch_in is not None and punch_out is not None:
        if punch_out <= punch_in:
            raise HTTPException(
                status_code=422,
                detail="Punch-out time must be after punch-in time",
            )

        if punch_out > punch_in + timedelta(hours=24):
            raise HTTPException(
                status_code=422,
                detail="Punch-out time cannot be more than 24 hours after punch-in",
            )

    # Recalculate derived fields; clients cannot set these directly.
    derived = {}

    if status in ("ABSENT", "LEAVE"):
        derived = {
            "late_minutes": 0,
            "overtime_minutes": 0,
            "work_hours": None,
            "half_day": False,
        }
    else:
        derived["late_minutes"] = (
            compute_late_minutes(
                punch_in,
                emp["shift_start"],
                emp["shift_end"],
            )
            if punch_in is not None
            else 0
        )

        if punch_in is not None and punch_out is not None:
            work_hours = compute_work_hours(punch_in, punch_out)

            derived.update({
                "work_hours": work_hours,
                "half_day": work_hours < 4.50,
                "overtime_minutes": compute_overtime(
                    punch_out,
                    emp["shift_start"],
                    emp["shift_end"],
                    record["date"],
                ),
            })
        else:
            derived.update({
                "work_hours": None,
                "half_day": False,
                "overtime_minutes": 0,
            })

    # Audit only the explicitly corrected fields that changed.
    history_changes = {
        key: {
            "from": record.get(key),
            "to": value,
        }
        for key, value in changes.items()
    }

    history_entry = {
        "at": datetime.now(timezone.utc).replace(microsecond=0),
        "by": body.regularized_by,
        "reason": body.reason,
        "changes": history_changes,
    }

    update_fields = {**changes, **derived}

    result = db.attendance_logs.update_one(
        {
            "_id": record["_id"],
        },
        {
            "$set": update_fields,
            "$push": {"history": history_entry},
        },
    )

    if result.matched_count == 0:
        raise HTTPException(
            status_code=404,
            detail="Attendance record not found",
        )

    updated = db.attendance_logs.find_one(
        {"_id": record["_id"]}
    )

    return attendance_response(updated)




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
    "$addFields": {
        "day_of_week": {
            "$dayOfWeek": {
                "date": {
                    "$dateFromString": {
                        "dateString": "$date",
                        "format": "%Y-%m-%d",
                        "timezone": "Asia/Kolkata"
                    }
                },
                "timezone": "Asia/Kolkata"
            }
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
            {
                "$and": [
                    {
                        "$in": [
                            "$status",
                            ["PRESENT", "WFH", "ON_DUTY"]
                        ]
                    },
                    {
                        "$in": [
                            "$day_of_week",
                            [2, 3, 4, 5, 6]
                        ]
                    }
                ]
            },
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

    data["total_work_hours"] = round_half_up(
        data["total_work_hours"], 2
    )

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
        {"$unwind": {
    "path": "$logs",
    "preserveNullAndEmptyArrays": True
}},
        {
            "$group": {
                "_id": "$logs.date",
                "present_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$in": [
                                    "$logs.status",
                                    ["PRESENT", "WFH", "ON_DUTY"]
                                ]
                            },
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
            attendance_rate = round_half_up(present_count / headcount, 4)
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
            round_half_up(sum(rates) / len(rates), 4)
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

        result = db.command(
            "explain",
            {
                "aggregate": "attendance_logs",
                "pipeline": pipeline,
                "cursor": {}
            },
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
        "$group": {
            "_id": "$department",
            "total_employees": {"$sum": 1}
        }
    }
]

        result = db.command(
        "explain",
        {
            "aggregate": "employees",
            "pipeline": pipeline,
            "cursor": {}
        },
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

        result = db.command(
            "explain",
            {
                "aggregate": "attendance_logs",
                "pipeline": pipeline,
                "cursor": {}
            },
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
                                {
                                    "$in": [
                                        "$logs.status",
                                        ["PRESENT", "WFH", "ON_DUTY"]
                                    ]
                                },
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

        result = db.command(
            "explain",
            {
                "aggregate": "employees",
                "pipeline": pipeline,
                "cursor": {}
            },
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
