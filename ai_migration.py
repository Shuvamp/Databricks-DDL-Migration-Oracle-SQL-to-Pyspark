# ai_migration.py

import requests
import time
import logging
import ast
import streamlit as st

# Configure Enterprise Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MigrationAI:
    def __init__(self, api_key, endpoint):
        self.api_key = api_key
        self.endpoint = endpoint


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

      interactive:
  sql:
    sql_script: 
      You are a database migration expert. Convert **Oracle SQL** into
      Databricks-compatible **Databricks SQL** (SQL-only).
      
      Output:
        - Return **Databricks SQL only**, each statement ends with a semicolon.
        - [MANDATORY] Do NOT wrap it in backticks, code fences, or a language tag.
      
      Key conversion considerations:
        - Remove or correct double quotes (`"Column"`)
        - [MANDATORY] If the source is NUMBER with no precision and no scale (e.g., NUMBER), always convert to INT.
        - [MANDATORY] If the source is NUMBER(p) with no scale (e.g., NUMBER(10)), always convert to DECIMAL(p).
        - [MANDATORY] If the source is NUMBER(p, s) with a scale (e.g., NUMBER(10,2)), always convert to DECIMAL(p, s).
        - [MANDATORY] Map Oracle NUMBER (with no precision and no scale) strictly to INT. Do NOT use DECIMAL for plain NUMBER columns.
        - Parameter markers (e.g., :param) are currently not allowed in the body of a CREATE VIEW statement in Databricks SQL. Do not Use parameters in CREATE VIEW. Use params in all other types of SQL.
        - Ensure all syntax is 100% compatible with the Databricks SQL engine on Databricks Runtime 14.x or newer.
        - Maintain the original logic, formatting, and comments from the source query.
        - Do not add any of your own commentary, explanations, or markdown formatting.
        - Return ONLY the raw, runnable Databricks SQL code.
        - DO NOT add ticks and `sql` keyword at the beginning and end of the conversions. Return just the converted SQL.
        - Replace variables with actual values in the procedure and instead of dynamic SQL Use regular queries. 
        - Only convert if the operation involves matching records between source and target tables
        - Do not convert simple single-table operations without joins or complex conditions
        - Change stored procedures to multi-line SQL statements, do not convert to a stored procedure.
      
      %%##conversion_prompts##%%
      %%##additional_prompts##%%
      
      --- START OF SQL ---
      {oracle_sql}
      --- END OF SQL ---

notebook:
  sql:
    sql_script: |
      You are a database migration expert. Convert Oracle SQL into a Databricks-compatible Databricks SQL notebook (SQL-only).
      
      Conversion rules:
      
      - Storage Clause Translation: Oracle-specific storage clauses (PARTITION BY RANGE/LIST/HASH, TABLESPACE, STORAGE) must be converted to Databricks SQL syntax.
      - Partitioning: Replace PARTITION BY RANGE (...) (...) blocks entirely. Extract the column name used in the range and apply it to a CLUSTER BY (column_name) clause at the end of the CREATE TABLE statement.
      - No Named Partitions: Remove all PARTITION <name> VALUES LESS THAN (...) syntax as it is not supported in Databricks. 
      - [MANDATORY] Try to not put special characters in variable names. If you have to include special characters in key, or include semicolon in value, please Use backquotes, e.g., SET `key`=`value`.
      - [MANDATORY] Table Storage: Every CREATE TABLE statement must explicitly include the USING DELTA clause before the closing semicolon. Do not change any other column definitions or logic while adding this clause
      - [MANDATORY] When converting to STRING or BINARY, remove any length specifications from the source. For example, RAW(16) must become BINARY, and UROWID(4000) or VARCHAR2(X) must become STRING.
      - [MANDATORY] Do not include parentheses or length values for Databricks native types (STRING, BINARY, INT, BOOLEAN)  
      - [MANDATORY] If any column in a CREATE TABLE statement uses the DEFAULT keyword, you must append the following property at the very end of the statement (after USING DELTA): TBLPROPERTIES('delta.feature.allowColumnDefaults' = 'supported')
      - [MANDATORY] Ensure the DEFAULT <value> stays within the column definition logic, and only the TBLPROPERTIES is added at the end.
      - [MANDATORY] Convert all variations of Oracle Timestamps (TIMESTAMP, TIMESTAMP WITH TIME ZONE, TIMESTAMP WITH LOCAL TIME ZONE) simply to TIMESTAMP.
      - Forbidden: Do NOT include CHECK or UNIQUE keywords inside the CREATE TABLE (...) parentheses.
      - [MANDATORY] Standalone ALTER TABLE is ONLY for CHECK and UNIQUE. All PRIMARY KEY and FOREIGN KEY must stay inside the CREATE TABLE block.
      - MANDATORY REMOVAL: Identify all CHECK and UNIQUE constraints. You MUST remove them from the body of the CREATE TABLE statement entirely.
      - MANDATORY ALTER: Generate each CHECK and UNIQUE constraint ONLY as a standalone ALTER TABLE statement appearing after the CREATE TABLE statement.
      - KEY PRESERVATION: Keep PRIMARY KEY and FOREIGN KEY inside the CREATE TABLE definition. Do not move them to ALTER.
      - [MANDATORY] Default Value Property: If any column definition within the CREATE TABLE statement contains the keyword DEFAULT, you MUST append the TBLPROPERTIES clause immediately following USING DELTA.
      - [MANDATORY] Syntax: Always use CREATE TABLE (do NOT use OR REPLACE).
      - The syntax must be: USING DELTA TBLPROPERTIES('delta.feature.allowColumnDefaults' = 'supported');
      - Convert all Oracle NCHAR(n) and NVARCHAR2(n) types to CHAR(n) and VARCHAR(n) respectively. Remove the N prefix but keep the fixed-length length logic.
      - Remove or correct double-quoted identifiers (e.g., "Column" → Column or `Column`).
      - Map types/functions to Databricks SQL: Maintain VARCHAR and CHAR types with their specified lengths (e.g., CHAR(10) remains CHAR(10))).
      - Ensure syntax is valid on Databricks SQL (DBR 14.x+).
      - Preserve original logic and formatting. Comments are allowed, but keep them  concise and in proper SQL comment syntax.
      - Parameter markers (e.g., :param) are currently not allowed in the body of a CREATE VIEW statement in Databricks SQL. Do not Use parameters in CREATE VIEW. Use params in all other types of SQL.
      - Convert separate INSERT/UPDATE/DELETE operations into a single MERGE statement. Focus on: 1) Proper join conditions, 2) WHEN MATCHED/NOT MATCHED logic, 3) Error handling, and 4) Performance optimization through single table access. For example:
          MERGE INTO target USING source
          ON target.key = source.key
          WHEN MATCHED AND target.marked_for_deletion THEN DELETE
          WHEN MATCHED THEN UPDATE SET target.updated_at = source.updated_at, target.value = DEFAULT
      - [MANDATORY] UPDATE in Databricks does not support FROM another table. For updating values from one table into another, Use MERGE. Do NOT Use `UPDATE ... FROM ...` under any circumstance.
      - Analyze DDLs and identify all tables with ''fact'' in their name (case-insensitive). For each fact table found, change the CREATE TABLE statement to include CLUSTER BY AUTO for automatic liquid clustering optimization in Databricks. For example:
          CREATE OR REPLACE TABLE ... (
          id INT,
          name STRING,
          value DOUBLE
          )
          CLUSTER BY AUTO;
      
      If certain procedural parts cannot be fully expressed in SQL-only form, produce the best possible SQL-only approximation using sequential cells, TEMP VIEWs, MERGE/INSERT/COPY INTO, and deterministic set-based steps.
      
      %%##conversion_prompts##%%
      %%##additional_prompts##%%
      
      --- START OF SQL ---
      {oracle_sql}
      --- END OF SQL ---

    procedure: |
      You are a Databricks migration assistant. Your task is to convert Oracle SQL stored procedures into
      Databricks-compatible **Databricks SQL notebooks** (SQL-only).
    
      Requirements:
        - Focus only on the **core business logic** (tables, transformations, DML/DDL).
        - **Do not** include logging, audit checkpoints, or procedural status updates.
        - **Do not** include explanations, prose, or unnecessary comments.
        - If the procedure has procedural loops/branches that cannot be expressed in SQL, refactor them into set-based SQL or split into multiple sequential cells with deterministic steps.
      
      HARD REQUIREMENTS (DO NOT SKIP):
        - [MANDATORY] `IDENTIFIER` usage is not allowed with (temporary) VIEWs. Change [TEMP] or regular VIEWs to just TABLEs [NOT temp] to Use IDENTIFIER. Use target_schema for creating tables.
        - [MANDATORY] Reference widgets as `:widget` or `IDENTIFIER(:widget || ''.table'')`. ${{widget}} usage is not allowed inside the stored procedure.
        - [MANDATORY] Try to not put special characters in variable names. If you have to include special characters in key, or include semicolon in value, please Use backquotes, e.g., SET `key`=`value`.
        - [MANDATORY] UPDATE in Databricks does not support FROM another table. For updating values from one table into another, Use MERGE. Do NOT Use `UPDATE ... FROM ...` under any circumstance.
    
      
      Widget usage:
        - Reference widgets directly in SQL as `:widget_name`.
        - For schema-qualified identifiers, Use `IDENTIFIER(:schema_widget || ''.object_name'')`, e.g.:
            SELECT * FROM IDENTIFIER(:source_schema || ''.orders'');
            CREATE OR REPLACE TABLE IDENTIFIER(:target_schema || ''.orders'') AS ...
        - Always wrap the object suffix (`.orders`) in single quotes inside the concatenation.
        - Use `:source_schema` for reads and non-DDL.
        - Use `:target_schema` for writes/DDL (only if DDL is present).
      
      Output format:
        - Output **SQL only** (no Python, no prose, no code fences).
        - Begin with the exact line:
            -- Databricks notebook source
        - Separate notebook cells with the exact line:
            -- COMMAND ----------
        - Place all widget definitions in the first cell, and nowhere else.
        - End every SQL statement with a semicolon.
        - Keep comments minimal (short headers only if needed).
      
      Databricks SQL compatibility:
        - [MANDATORY] `IDENTIFIER` usage is not allowed with (temporary) VIEWs. Change [TEMP] or regular VIEWs to just TABLEs [NOT temp] to Use IDENTIFIER. Use target_schema for creating tables.
        - [MANDATORY] Reference widgets as `:widget` or `IDENTIFIER(:widget || ''.table'')`. ${{widget}} usage is not allowed inside the stored procedure.
        - [MANDATORY] Try to not put special characters in variable names. If you have to include special characters in key, or include semicolon in value, please Use backquotes, e.g., SET `key`=`value`.
        - Translate vendor-specific types and functions to Databricks SQL equivalents:
            - `VARCHAR` → `VARCHAR'
            - `NUMBER` → `DECIMAL` or `INT`
            - `GETDATE` → `CURRENT_TIMESTAMP`
        - Use Databricks SQL constructs:
            - `CREATE OR REPLACE TEMP VIEW ... AS SELECT ...` for staging
            - `MERGE INTO` for upserts
        - Remove or rewrite unsupported procedural code (cursors, while loops, etc.) into set-based logic.
        - Parameter markers (e.g., :param) are currently not allowed in the body of a CREATE VIEW statement in Databricks SQL. Do not Use parameters in CREATE VIEW. Use params in all other types of SQL.
        - Convert separate INSERT/UPDATE/DELETE operations into a single MERGE statement. Focus on: 1) Proper join conditions, 2) WHEN MATCHED/NOT MATCHED logic, 3) Error handling, and 4) Performance optimization through single table access. For example:
            MERGE INTO target USING source
            ON target.key = source.key
            WHEN MATCHED AND target.marked_for_deletion THEN DELETE
            WHEN MATCHED THEN UPDATE SET target.updated_at = source.updated_at, target.value = DEFAULT
        - [MANDATORY] UPDATE in Databricks does not support FROM another table. For updating values from one table into another, Use MERGE. Do NOT Use `UPDATE ... FROM ...` under any circumstance.
        - Analyze DDLs and identify all tables with ''fact'' in their name (case-insensitive). For each fact table found, change the CREATE TABLE statement to include CLUSTER BY AUTO for automatic liquid clustering optimization in Databricks. For example:
            CREATE OR REPLACE TABLE ... (
            id INT,
            name STRING,
            value DOUBLE
            )
            CLUSTER BY AUTO;
      
        %%##conversion_prompts##%%
        %%##additional_prompts##%%
      
      --- START OF SQL ---
      {oracle_sql}
      --- END OF SQL ---

  python:
    sql_script: |
      You are a database migration expert. Convert **Oracle SQL** into
      Databricks-compatible **Databricks Python notebook** (.py source format).
      
      Executing SQL:
        - For every SQL statement, wrap it in a Python cell using:
            spark.sql(f""""<converted SQL>"""")
          (Ensure proper indentation. **Every SQL statement must end with a semicolon** inside the triple quotes.)
        - Use **f-strings** to interpolate Python variables (e.g., `{source_schema}`) directly in SQL.
        - Use **SQL comment syntax (`--` or `/* ... */`) inside spark.sql blocks**.
          Use **Python comments (`#`)** only for comments outside SQL blocks.
      
      REQUIREMENTS:
        UPDATE in Databricks does not support FROM another table. For updating values from one table into another, Use MERGE. Do NOT Use `UPDATE ... FROM ...` under any circumstance.
      
      Widget usage:
        - Use the Python variables created from widgets (`source_schema`, `target_schema`) when constructing identifiers. For example:
            spark.sql(f""""SELECT * FROM {source_schema}.orders;"""")
            spark.sql(f""""MERGE INTO {target_schema}.orders AS tgt USING {source_schema}.orders_src AS src ON ... WHEN MATCHED THEN"""")
        - Replace hard-coded `catalog.schema.table` references with:
            - `{source_schema}.<object_name>` when **reading** or for non-DDL.
            - `{target_schema}.<object_name>` when **writing/creating/altering** (DDL only).
          Keep the original object names.
       
      
      Procedural logic:
        - Where procedural behavior is required (loops, branching, variables), express it in **native Python** cells.
        - Keep SQL set-based where possible; Use sequential cells, TEMP VIEWs, MERGE/INSERT/COPY INTO for approximations when needed.
        
        %%##conversion_prompts##%%
        %%##additional_prompts##%%
      
      --- START OF SQL ---
      {oracle_sql}
      --- END OF SQL ---

    procedure: |
      You are a Databricks migration assistant. Your task is to convert Oracle SQL stored procedures into
      Databricks-compatible **Databricks Python notebooks** (.py source format).
  
      Requirements:
        - Convert procedural loops and branches into native Python constructs (for/while loops, if/else).
        - Use PySpark for orchestration (control flow, dynamic SQL execution).
        - Use `spark.sql("""" ... """")` for all set-based SQL queries, inserts, updates, deletes, and merges.
        - Each SQL statement must end with a semicolon inside the triple quotes.
      
      HARD REQUIREMENTS (DO NOT SKIP):
        - [MANDATORY] UPDATE in Databricks does not support FROM another table. For updating values from one table into another, Use MERGE. Do NOT Use `UPDATE ... FROM ...` under any circumstance.
      
      Widget rules (MANDATORY):
        - The **first two cells must handle widgets only**:
            - **First cell**: all widget definitions using `dbutils.widgets.text(...)`. Example:
                                dbutils.widgets.text("source_schema", "main.source")
                                dbutils.widgets.text("as_of_date", "2024-01-01")
            - **Second cell**: all widget retrievals using `var = dbutils.widgets.get("...")`. Example:
                                 source_schema = dbutils.widgets.get("source_schema")
                                 as_of_date = dbutils.widgets.get("as_of_date")
        - Always include a `source_schema` widget definition in the first cell and retrieval in the second cell:
            dbutils.widgets.text("source_schema", "main.source")
            source_schema = dbutils.widgets.get("source_schema")
        - Conditionally include a `target_schema` widget **only if the procedure performs DDL** (CREATE/ALTER/DROP/TRUNCATE/RENAME/COMMENT/CREATE SCHEMA/CREATE VIEW/TABLE/FUNCTION/PROCEDURE):
            dbutils.widgets.text("target_schema", "main.target")
            target_schema = dbutils.widgets.get("target_schema")
        - For every input parameter or variable in the stored procedure, create a widget with a realistic default value.
        - Use the same variable names as in the procedure. Do **not** create unUsed widgets.
      
      
      Output format:
        - Output **Python notebook code only** (no prose, no markdown).
        - Begin with the exact line:
          # Databricks notebook source
        - Separate notebook cells with the exact line:
          # COMMAND ----------
        - First cell = widget definitions, second cell = widget retrievals, then remaining cells for business logic.
        - Keep the result concise: focus on the core business logic (tables, transformations, DML/DDL).
        - Keep comments minimal (short headers only if needed).
      
      Databricks SQL compatibility:
        - Translate vendor-specific types and functions to Databricks SQL equivalents:
            Databricks SQL compatibility:
        - [MANDATORY] Data Type Mapping:
            - Oracle `NUMBER` (no p,s) -> `INT`
            - Oracle `NUMBER(p,s)` -> `DECIMAL(p,s)`
            - Oracle `NCHAR/NVARCHAR` -> `CHAR/VARCHAR` (Remove 'N' prefix)
            - Oracle `TIMESTAMP` (all variants) -> `TIMESTAMP`
            - Oracle `GETDATE` -> `CURRENT_TIMESTAMP`
        - [MANDATORY] Constraint Placement:
            - Keep PRIMARY KEY and FOREIGN KEY inside CREATE TABLE.
            - Move CHECK and UNIQUE to standalone ALTER TABLE statements.
        - [MANDATORY] No `UPDATE FROM`: Use `MERGE INTO` for all multi-table updates or upserts.
        - [MANDATORY] Storage: Every CREATE TABLE must use `USING DELTA`. If `DEFAULT` is present, add `TBLPROPERTIES('delta.feature.allowColumnDefaults' = 'supported')`.
        - Fact Table Optimization: For tables with 'fact' in the name, append `CLUSTER BY AUTO`.
      
        %%##conversion_prompts##%%
        %%##additional_prompts##%%
      
      --- START OF SQL ---
      {oracle_sql}
      --- END OF SQL ---

workflow:
  sql:
    sql_script: |
      You are a Databricks migration assistant. Convert the following Oracle SQL script (a sequence of SQL statements separated by semicolons) into a set of
      Databricks-compatible **SQL notebooks** (SQL-only), suitable to be orchestrated as parallel tasks in a Databricks Workflow DAG.
  
      GOAL
        - Split the script into the minimal set of **independent, idempotent** SQL notebooks that can run in parallel where safe.
        - For each notebook (task), return: a task-safe **name**, the SQL **content**, its **dependencies**, and its **parameters** (widgets) Used by that task only.
        - Produce a single JSON manifest describing the DAG and the notebooks’ contents.
  
      SPLITTING & DEPENDENCY RULES
        - Split at semicolons into statements, then group into tasks:
            - One notebook per durable side effect (DDL or DML).
            - Keep statements together if they depend on TEMP VIEWs or require strict order.
        - Dependencies:
            - If notebook B Uses an object created/modified in notebook A, then B depends_on A.
        - Prefer **parallel execution** where safe.
        - Normalize to Databricks SQL (DBR 14.x+): types, functions, and syntax. End every statement with `;`.
        - Ensure every notebook is **idempotent**. End each with `;`.
  
      NAMING
        - task_name: lower_snake_case, concise, reflects the durable output (e.g., dim_customer_build, load_fact_sales).
        - Keep object names as in source (only schema/casing normalization as required by Databricks SQL).
  
      OUTPUT FORMAT (MANDATORY)
        - Return one JSON object **only**.
        - Do NOT wrap it in backticks, code fences, or a language tag.
        - Do NOT prepend or append any extra text (like "Here is the JSON:").
        - The response must start with ''{'' and end with ''}''.
            {
              "workflow_name": "<concise_workflow_name>",
              "tasks": [
                {
                  "task_name": "<lower_snake_case>",
                  "depends_on": ["<other_task_name>", ...],
                  "parameters": {
                    "source_schema": "main.source",
                    "target_schema": "main.target",   // include ONLY if this task’s SQL has DDL
                    "<other_var>": "<value>"          // only if Used in THIS task
                  },
                  "content": "<full SQL notebook content with header + cells per rules>"
                }
              ]
            }
  
      CONSTRAINTS
        - [MANDATORY] `IDENTIFIER` usage is not allowed with (temporary) VIEWs. Change [TEMP] or regular VIEWs to just TABLEs [NOT temp] to Use IDENTIFIER. Use target_schema for creating tables.
        - [MANDATORY] Reference widgets as `:widget` or `IDENTIFIER(:widget || ''.table'')`. ${{widget}} usage is not allowed inside the stored procedure.
        - Do not include any global widgets block; only per-task `parameters`.
        - `parameters` must be a dictionary, not a list.
        - Do not include `include_if_ddl`.
        - Each task’s `parameters` must match the widgets defined in its content.
        - [MANDATORY] Try to not put special characters in variable names. If you have to include special characters in key, or include semicolon in value, please Use backquotes, e.g., SET `key`=`value`.
        - The "content" of each task must be a **complete SQL notebook** obeying the content rules.
        - Only include widgets actually Used by the task notebook (except source_schema; always include. target_schema only if DDL exists).
        - Do not emit Python. Do not include code fences or extra text outside the single JSON.
        - !!! IMPORTANT: Output raw JSON only. Do not Use ```json or ``` fencing. Do not include any prose before or after. !!!
        - Convert separate INSERT/UPDATE/DELETE operations into a single MERGE statement. Focus on: 1) Proper join conditions, 2) WHEN MATCHED/NOT MATCHED logic, 3) Error handling, and 4) Performance optimization through single table access. For example:
            MERGE INTO target USING source
            ON target.key = source.key
            WHEN MATCHED AND target.marked_for_deletion THEN DELETE
            WHEN MATCHED THEN UPDATE SET target.updated_at = source.updated_at, target.value = DEFAULT
        - [MANDATORY] UPDATE in Databricks does not support FROM another table. For updating values from one table into another, Use MERGE. Do NOT Use `UPDATE ... FROM ...` under any circumstance.
        - Analyze DDLs and identify all tables with ''fact'' in their name (case-insensitive). For each fact table found, change the CREATE TABLE statement to include CLUSTER BY AUTO for automatic liquid clustering optimization in Databricks. For example:
            CREATE OR REPLACE TABLE ... (
            id INT,
            name STRING,
            value DOUBLE
            )
          CLUSTER BY AUTO;
  
      %%##conversion_prompts##%%
      %%##additional_prompts##%%
  
      --- START OF SQL SCRIPT ---
      {oracle_sql}
      --- END OF SQL SCRIPT ---

    procedure: |
      You are a Databricks migration assistant. Convert the following Oracle stored procedure into a set of
      Databricks-compatible **SQL notebooks** (SQL-only), suitable to be orchestrated as parallel tasks in a Databricks Workflow DAG.
      
      GOAL
        - Split the procedure into the minimal set of **independent, idempotent** SQL notebooks that can run in parallel where safe.
        - For each notebook (task), return: a task-safe **name**, the SQL **content**, its **dependencies** (tasks it must run after), and its **parameters** (widgets) Used by that task only.
        - Produce a single JSON manifest describing the DAG and the notebooks’ contents (see Output Format).
        
      SPLITTING & DEPENDENCY RULES
        - Split at **data dependencies / side effects**:
            - One notebook per unit that produces a durable output (CREATE/ALTER/DROP/TRUNCATE/RENAME/COMMENT/CREATE SCHEMA/VIEW/TABLE/FUNCTION/PROCEDURE; MERGE/INSERT/DELETE/UPDATE).
            - Keep steps that share **TEMP VIEWs** or require **statement ordering** in the same notebook.
        - Infer dependencies by object flow:
            - If notebook B **reads** an object created/modified in notebook A, then B dependsOn A.
            - All DDL that creates/alter schemas/tables must precede DML that Uses them.
            - Avoid splitting inside a single transaction/atomic semantic (treat as one notebook).
        - Prefer **maximal parallelism** without violating correctness.
      
        - task_name: lower_snake_case, concise, reflects the durable output (e.g., dim_customer_build, load_fact_sales).
        - Keep object names as in source (only schema/casing normalization as required by Databricks SQL).
        
      OUTPUT FORMAT (MANDATORY)
        - Return one JSON object **only**.
        - Do NOT wrap it in backticks, code fences, or a language tag.
        - Do NOT prepend or append any extra text (like "Here is the JSON:").
        - The response must start with ''{'' and end with ''}''.
            {
              "workflow_name": "<concise_workflow_name>",
              "tasks": [
                {
                  "task_name": "<lower_snake_case>",
                  "depends_on": ["<other_task_name>", ...],
                  "parameters": {
                    "source_schema": "main.source",
                    "target_schema": "main.target",   // include ONLY if this task’s SQL has DDL
                    "<other_var>": "<value>"          // only if Used in THIS task
                  },
                  "content": "<full SQL notebook content with header + cells per rules>"
                }
              ]
            }
      
      %%##conversion_prompts##%%
      %%##additional_prompts##%%
  
      --- START OF SQL PROCEDURE ---
      {oracle_sql}
      --- END OF SQL PROCEDURE ---



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
