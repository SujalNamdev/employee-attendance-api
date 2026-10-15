# DECISIONS.md

**1. Indexes:** I created a compound index on `date` (descending) and `emp_code` (ascending) to support attendance listing and sorting. A unique index on `emp_code` and a unique compound index on `emp_code` plus `date` should also enforce employee and daily attendance uniqueness. I would reject unnecessary indexes that duplicate existing ones because they increase write overhead.

**2. Punch-in race:** My current code checks for an existing attendance record before inserting. If two identical requests arrive simultaneously, both could pass the check and insert duplicates. A unique compound index on `emp_code` and `date`, combined with handling MongoDB duplicate-key errors as HTTP 409, is needed to prevent this reliably.

**3. Ties:** The leaderboard uses MongoDB ranking by total late minutes. Employees tied at the cutoff should all be returned because the limit applies to rank, not the number of employees. Equal totals should receive equal ranks.

**4. Headcount:** The department summary should start from employees rather than attendance logs, then include attendance statistics. This ensures employees without logs are counted.

**5. Scaling:** For 100 times more data, I would review query execution plans, optimize indexes, and test aggregation performance against a larger dataset.
