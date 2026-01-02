# ai_migiration.py

import requests
import time
import logging
import ast
import streamlit as st

# Configure Enterprise Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MigrationAI:
    def __init__(self, api_key):
        self.api_key = api_key

    # Universal call to Databricks endpoint using session state settings
    def call_llama(self, prompt):
        # Get settings from session state
        settings = st.session_state.model_settings
        api_url = settings["endpoint"]
        temperature = settings["temperature"]
        max_tokens = settings["max_tokens"]
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        retries = 3
        for attempt in range(retries):
            try:
                logger.info(f"Sending request to {settings['model']} (Attempt {attempt + 1}/{retries})...")
                response = requests.post(api_url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                raw_content = data["choices"][0]["message"]["content"]
                
                # Handle new format where content is a list
                if isinstance(raw_content, list):
                    text_content = ""
                    for item in raw_content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text_content += item.get("text", "")
                    return self._clean_model_output(text_content)
                else:
                    return self._clean_model_output(raw_content)
            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed: {str(e)}")
                if attempt == retries - 1:
                    return f"Error after {retries} attempts: {str(e)}"
                time.sleep(2 ** attempt)  # Exponential backoff

    def _clean_model_output(self, content):
        """Parses and cleans the model output if it contains structured reasoning traces."""
        if not content:
            return ""
            
        # Check for the specific structured format (lines of python-dict strings)
        if "{'type': 'reasoning'" in content or "{'type': 'text'" in content:
            full_text = ""
            found_structured = False
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        data = ast.literal_eval(line)
                        if data.get('type') == 'text':
                            full_text += data.get('text', '')
                        found_structured = True
                    except:
                        pass
            
            if found_structured:
                return full_text
                
        return content

    # ------------------------------
    # SQL Migration Functions
    # ------------------------------
    def migrate_schema(self, oracle_sql, **kwargs):
        # Handle large files by chunking
        if len(oracle_sql) > 8000:  # Characters threshold for chunking
            return self._process_large_sql(oracle_sql, **kwargs)
            
        prompt = f"""
 Act as an expert SQL-to-Databricks migration specialist. Convert the provided Oracle DDL to Databricks SQL with 100% precision.

**1. CONSTRAINT & STRUCTURE RULES:**

* **Table-Level Constraints:** Define PRIMARY KEY, UNIQUE, or FOREIGN KEY as Table-Level Constraints ONLY IF they are present in the source Oracle DDL. If the source has no PK, do not generate a constraint block.
* **Format:** If present, place at the end of the column list using: CONSTRAINT PK_[COLUMN_NAME] PRIMARY KEY (column_name).
* **Nullability:** if the Columns in PKs or Unique constraints MUST be explicitly defined as `NOT NULL`.
* **No Enforcement:** Do NOT include `ENFORCED` or `NOT ENFORCED` keywords.
* **Termination:** End every `CREATE TABLE` statement with **`USING DELTA;`**.
* **Inlining:** Keep `DEFAULT` values and `NOT NULL` constraints inline; strip all Oracle storage clauses (TABLESPACE, PCTFREE, STORAGE, etc.).
* **Clean DDL:** Do not use `ALTER TABLE` or `TBLPROPERTIES` for constraints or defaults.
    No Inference: Do not infer, synthesize, or assume any constraints. If the source Oracle DDL does not contain CONSTRAINT, PRIMARY KEY, UNIQUE, or FOREIGN KEY, do not generate any constraints.
    No PK by Naming: Do not treat columns named *_ID or similar as primary keys unless the source explicitly declares a PK.
    Nullability: Do not add NOT NULL unless it is explicitly present in the source column definition.
    Exact Reflection: Constraints must be a verbatim reflection of the source. If absent, output none.
* **Schema Handling: If the source uses "SCHEMA"."TABLE", output only the table name, without the schema prefix If the source has no PK, do not generate a NOT NULL.(e.g., convert "CONTRACT_SYS"."CONTRACT_TERM_INFO" → CONTRACT_TERM_INFO).
    Quotation Removal: Remove all double quotes from identifiers, including table names, column names, and role/user names. 
    GRANT Statements: Retain all GRANT statements from the source, but remove any surrounding double quotes from the object and principal names.


**2. STRICT DATA TYPE MAPPING:**

* `NUMBER(p, s)` -> `DECIMAL(p, s)` (Mandatory: Do NOT use INT/BIGINT)
* `VARCHAR2(n)` / `CHAR(n)` -> `VARCHAR(n)` / `CHAR(n)` (Mandatory: Do NOT use STRING)
* `BFILE` -> `STRING`
* `LONG RAW` / `BLOB` /  -> `BINARY`
* `VARRAY` -> `ARRAY<STRING>`
* `INTERVAL DAY TO SECOND` -> `INTERVAL DAY TO SECOND`
* `INTERVAL YEAR TO MONTH` -> `INTERVAL YEAR TO MONTH`
* `TIMESTAMP WITH TIME ZONE` -> `TIMESTAMP`
* `DATE` / `TIMESTAMP` -> `DATE` / `TIMESTAMP`
*  `SDO_GEOMETRY` -> `GEOMETRY`

**3. OUTPUT FORMAT:**
For each table, provide:

1. **Converted Code:** Single markdown block with the Databricks SQL.
2. **Mapping Summary:** A brief list of specific type and constraint changes.
3. **Confidence Level:** HIGH/MEDIUM/LOW based on syntax complexity.

**4. EXECUTION COMMAND:**
"Apply this production migration pipeline to the provided Oracle SQL. Strictly map types according to the matrix, move keys to table-level, and terminate with 'USING DELTA;'. Do not provide external ALTER TABLE statements."

**Input (Oracle):**
[INSERT ORACLE SQL HERE]

**Output Format:**
1. Provide the **pysql** code in a single markdown block (```sql ... ```).
2. After the code block, provide a section titled "### Changes and Enhancements" where you list the specific changes made, optimizations applied, and any reasoning.

**Input (Oracle):**

{oracle_sql}

**Output (Databricks):**
"""
        return self.call_llama(prompt)

    def _process_large_sql(self, oracle_sql, **kwargs):
        """Process large SQL files by splitting into manageable chunks"""
        import re
        
        # Split by CREATE statements
        statements = re.split(r'(?i)\b(CREATE\s+(?:TABLE|VIEW|PROCEDURE|FUNCTION))', oracle_sql)
        chunks = []
        current_chunk = ""
        
        for i in range(0, len(statements), 2):
            if i + 1 < len(statements):
                statement = statements[i] + statements[i + 1]
                if len(current_chunk + statement) > 6000:
                    if current_chunk:
                        chunks.append(current_chunk)
                    current_chunk = statement
                else:
                    current_chunk += statement
        
        if current_chunk:
            chunks.append(current_chunk)
        
        # Process each chunk
        results = []
        for i, chunk in enumerate(chunks):
            logger.info(f"Processing chunk {i+1}/{len(chunks)}")
            result = self.migrate_schema(chunk, **kwargs)
            results.append(result)
        
        # Combine results
        combined_sql = ""
        combined_changes = "### Changes and Enhancements\n"
        
        for result in results:
            if "```sql" in result:
                sql_match = re.search(r"```sql(.*?)```", result, re.DOTALL)
                if sql_match:
                    combined_sql += sql_match.group(1).strip() + "\n\n"
            
            changes_match = re.search(r"### Changes and Enhancements(.*)", result, re.DOTALL)
            if changes_match:
                combined_changes += changes_match.group(1).strip() + "\n"
        
        return f"```sql\n{combined_sql}```\n\n{combined_changes}"

    def migrate_procedure(self, oracle_procedure, **kwargs):
        prompt = f"""
You are an expert Oracle-to-Databricks SQL migration specialist. Your priority is accurate SQL-to-SQL conversion, strict data type preservation, constraint correctness, and production-grade migration output.

Your output MUST follow the rules below with zero exceptions.

====================================================
SECTION 1 — CRITICAL CONSTRAINT RULES (STRICT)
==============================================

These rules override all others. Follow exactly.

1. UNIQUE CONSTRAINTS

    * Databricks does NOT enforce UNIQUE constraints unless manually enabled.
    * REMOVE all UNIQUE constraints from DDL.
    * Add comment: "UNIQUE removed — unsupported unless enabled".
    * If uniqueness required: recommend NOT NULL + CHECK or ETL-layer logic.

2. PRIMARY KEY CONSTRAINTS

    * Databricks treats PRIMARY KEY as INFORMATIONAL ONLY.
    * Keep PK as COMMENT-style metadata only.
    * **DO NOT generate enforced PK constraints.**
    * **If enforcement required: replace with NOT NULL + CHECK.** (Reinforcement of the new requirement)

3. FOREIGN KEYS

    * Databricks does NOT enforce FK constraints.
    * Convert all foreign keys to COMMENT-only definitions.
    * Document that RI must be handled externally.

4. CHECK CONSTRAINTS

    * Databricks supports only simple CHECK conditions.
    * Validate each CHECK for compatibility.
    * If unsupported → convert to COMMENT +
      `/* REVIEW REQUIRED: CHECK constraint not supported */`.
    * **CRITICAL PLACEMENT RULE: CHECK constraints must be added via `ALTER TABLE ADD CONSTRAINT` after the table is created. DO NOT include them in the `CREATE TABLE` statement.** (New requirement added)

5. REVIEW MARKERS

    * If ANY constraint conversion is uncertain:
      `/* REVIEW REQUIRED: Constraint unclear */`.

6. OUTPUT FORMAT FOR CONSTRAINTS
    Each constraint conversion MUST show:
    /* ORIGINAL: <Oracle constraint>
    */
    /* NOTES:
    - <explanation of replacements/removals>
    */

====================================================
SECTION 2 — DATA TYPE RULES (STRICT)
====================================

1. WIDTH, PRECISION, SCALE

    * **Oracle datatype sizes MUST be preserved exactly where possible, matching the Databricks SQL type size.** (Refined for emphasis)
    * NUMBER(p,s), VARCHAR2(n), CHAR(n), DATE, TIMESTAMP must retain identical structure in Databricks.

2. STRING vs VARCHAR

    * DEFAULT: Use VARCHAR, not STRING.
    * STRING allowed ONLY if VARCHAR cannot represent the source length.
    * ALWAYS provide justification when using STRING.

3. DATE DEFAULTS

    * **DATE column default MUST be `CURRENT_DATE`.** (Emphasized new requirement)
    * **NEVER use `CURRENT_TIMESTAMP` for DATE fields, as it returns a TIMESTAMP type.** (Emphasized new requirement)

4. BINARY, BLOB, CLOB

    * Convert using Databricks-supported binary types.
    * Document performance considerations.

====================================================
SECTION 3 — CONVERSION STRATEGY PRIORITY
========================================

1. SQL-to-SQL (>= 90% compatibility)

    * MUST prefer SQL-to-SQL conversion.
    * Keep logic identical unless required by platform differences.

2. Hybrid SQL + Python (70–89% SQL compatibility)

    * Allowed ONLY when SQL cannot cover entire logic.
    * Python ≤ 10% of logic.
    * MUST document why Python was required.

3. PySpark (< 70% SQL compatibility)

    * Use only as LAST resort.
    * Maintain SQL-like readability.
    * Add detailed migration notes.

====================================================
SECTION 4 — TESTING SEQUENCE (MANDATORY)
========================================

Perform conversions in the following order:
Phase 1: DDL (tables, indexes, constraints)
Phase 2: CTE-heavy queries (nested queries, WITH clauses)
Phase 3: Stored procedures (loops, conditions, business logic)
Phase 4: Packages (dependencies, cross-references)

====================================================
SECTION 5 — REQUIRED OUTPUT FORMAT
==================================

You MUST output:

1. Original Oracle code (commented out).
2. Converted Databricks code (including separate `ALTER TABLE` for CHECK constraints).
3. Confidence Level: HIGH / MEDIUM / LOW.
4. `/* REVIEW REQUIRED */` marking unclear areas.
5. Detailed datatype justification.
6. Detailed constraint explanation.
7. Test steps for validating conversion.
8. Performance considerations.
9. Deployment checklist items (DDL, data types, constraints, indexes).

====================================================
SECTION 6 — STRESS TEST REQUIREMENTS
====================================

You MUST ensure conversion supports:

* BLOB/CLOB handling
* 1000+ line JOIN operations
* Deep nested subqueries
* Multi-level CTEs
* Complex OUTER JOIN patterns
* Multi-package dependencies

====================================================
SECTION 7 — FOLDER STRUCTURE REQUIREMENTS
=========================================

source-scripts/       → Original Oracle SQL
converted-code/       → Databricks SQL with review flags
test-results/         → Execution and validation logs
documentation/        → Mapping decisions & constraint notes
stress-tests/         → Large query & BLOB cases

====================================================
SECTION 8 — SUCCESS METRICS
===========================

* 100% constraint accuracy
* Oracle datatype sizes preserved
* Minimal STRING usage
* Review flags only in uncertain cases
* All phases tested
* Stress tests passed
* Full documentation completed

====================================================
FINAL EXECUTION COMMAND
=======================

"Apply this entire migration pipeline to convert [SOURCE_DATABASE] to Databricks. Preserve datatypes exactly, enforce VARCHAR over STRING, use CURRENT_DATE for DATE defaults, remove UNIQUE constraints, convert PK/FK to informational comments, enforce constraints using NOT NULL + CHECK where needed, ensure **CHECK constraints are added via separate ALTER TABLE statements**, follow SQL-first strategy, and output all required documentation and testing steps."
**Output Format:**
1. Provide the **Databricks SQL** code in a single markdown block (```sql ... ```).
2. After the code block, provide a section titled "### Changes and Enhancements" where you list the specific changes made, optimizations applied, and any reasoning.

**Input (Oracle):**
{oracle_procedure}

**Output (Databricks):**
"""
        return self.call_llama(prompt, **kwargs)

    def optimize_query(self, sql_query, **kwargs):
        prompt = f"""
Optimize the following SQL query for Databricks Spark SQL performance.

### Optimization Strategies:
1. **Explicit Joins**: Convert comma-separated joins (ANSI-89) to explicit `JOIN ... ON` (ANSI-92).
2. **Selectivity**: Avoid `SELECT *`; list specific columns.
3. **Filtering**: Push `WHERE` clauses as close to the source tables as possible.
4. **CTEs**: Use Common Table Expressions (WITH clauses) for readability and potential reuse.
5. **Window Functions**: Use window functions instead of self-joins where applicable.

### Example:

**Input:**
SELECT * FROM orders o, customers c 
WHERE o.cust_id = c.id AND c.region = 'US';

**Optimized:**
SELECT 
  o.order_id,
  o.order_date,
  c.name AS customer_name
FROM orders o
JOIN customers c ON o.cust_id = c.id
WHERE c.region = 'US';

---

**Output Format:**
1. Provide the **Optimized SQL** code in a single markdown block (```sql ... ```).
2. After the code block, provide a section titled "### Changes and Enhancements" where you list the specific changes made, optimizations applied, and any reasoning.

**Input:**
{sql_query}

**Optimized Query:**
"""
        return self.call_llama(prompt, **kwargs)

    def generate_streamlit_code(self, requirements, **kwargs):
        prompt = f"""
Generate Streamlit code based on these requirements:

{requirements}

Include:
- Secure DB connection
- Query execution UI
- Error handling
- Dataframe display

Streamlit Code:
"""
        return self.call_llama(prompt, **kwargs)

    def get_enterprise_capabilities(self):
        """Returns a summary of enterprise features for documentation."""
        return {
            "Model": "databricks-gpt-oss-120b",
            "Features": [
                "Few-Shot Prompting for High Accuracy",
                "Exponential Backoff Retry Logic",
                "Structured Enterprise Logging",
                "Unity Catalog Compliance",
                "Delta Lake Optimization Rules"
            ],
            "Supported Conversions": [
                "Oracle DDL -> Databricks Delta DDL",
                "PL/SQL -> Databricks SQL Procedures",
                "Legacy SQL -> Spark Optimized SQL"
            ]
        }
