# DECISIONS.md

This document explains the main technical decisions and trade-offs made while implementing the Employee Attendance & Analytics API.

## 1. Database Indexes

I created a unique index on `emp_code` in the employees collection to prevent duplicate employee records.

I also created a unique compound index on `emp_code` and `date` in the attendance_logs collection to ensure that an employee cannot have multiple attendance records for the same date.

A compound index on `date` (descending) and `emp_code` (ascending) supports attendance listing and sorting.

I avoided unnecessary indexes that duplicate existing ones because additional indexes increase storage requirements and write overhead.

## 2. Punch-in Concurrency

Checking for an existing attendance record before insertion is not sufficient to prevent duplicates when multiple requests arrive simultaneously.

To handle this, I use a unique compound index on `emp_code` and `date`. The punch-in endpoint also handles MongoDB duplicate-key errors and returns HTTP 409 Conflict.

This allows the database to enforce uniqueness even when concurrent requests pass the initial existence check.

## 3. Leaderboard Ties

Employees with equal total late minutes should receive equal ranks.

The leaderboard should also include all employees tied at the cutoff rank rather than arbitrarily excluding employees because of a fixed result count.

This ensures that the ranking reflects actual performance rather than the order in which records happen to be returned.

## 4. Department Headcount

Department attendance trends must include employees who joined by the relevant date, even if they have no attendance records.

For this reason, the department trend aggregation starts from the employees collection and uses a lookup to retrieve matching attendance records.

The headcount is calculated using employees whose `joined_on` date is on or before the date being evaluated.

This prevents employees without attendance logs from being excluded from department headcount calculations.

## 5. Scaling Considerations

If the dataset grows significantly, I would review MongoDB execution plans and execution statistics to identify inefficient queries.

I would also evaluate index usage, optimize aggregation pipelines, and benchmark performance using a larger dataset.

Any additional indexes would be introduced based on actual query patterns and measured performance rather than added unnecessarily.
