import duckdb
from app.agent.state import AgentState
from e2b_code_interpreter import Sandbox
import duckdb


async def run(state: AgentState) -> AgentState:
    if state.code_language == "sql":
        con = duckdb.connect()
        con.execute(f"CREATE VIEW df AS SELECT * FROM read_parquet('{state.parquet_path}')")
        
        try:
            result_df = con.execute(state.generated_code).df()
            result = result_df.to_dict(orient="records")
            return state.model_copy(update={
                "execution_result": result,
                "execution_error": "",
            })
        except Exception as e:
            return state.model_copy(update={
                "execution_error": str(e),
                "retry_count": state.retry_count + 1,
                "execution_result": None,
            })
    else:
        print(state.generated_code)
        sandbox = Sandbox.create()
        execution = sandbox.run_code(state.generated_code)
        if execution.error:
            # execution.error is an e2b 'ExecutionError' object, must cast to string
            error_str = f"{execution.error.name}: {execution.error.value}" if hasattr(execution.error, 'name') else str(execution.error)
            return state.model_copy(update={
                "execution_error": error_str,
                "retry_count": state.retry_count + 1,
                "execution_result": None
            })
        output = execution.logs.stdout

        if not output:
            return state.model_copy(update={
                "execution_error": "The code ran successfully but there is no output, make sure to add an output",
                "retry_count": state.retry_count + 1,
                "execution_result": None
            })
        else:
            return state.model_copy(update={
                "execution_result": output,
                "execution_error": ""
            })