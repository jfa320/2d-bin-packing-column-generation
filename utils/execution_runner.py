"""Parent-owned wall deadline and continuously drained worker results."""

import math
import multiprocessing
from queue import Empty, Queue
from threading import Thread
from time import perf_counter

from utils.execution_result import ExecutionResult
from utils.paver_constants import PaverConstants


PAVER = PaverConstants


class _ResultWriter:
    def __init__(self, connection):
        self.connection = connection

    def put(self, message):
        self.connection.send(message)


def _run_worker(target, writer, max_time, instance, model_name):
    try:
        target(_ResultWriter(writer), max_time, instance)
    except BaseException as exc:
        writer.send(ExecutionResult(
            instance["case_name"], model_name, None, PAVER.TERMINATION_ERROR, None, 0.0,
            error_message=f"{type(exc).__name__}: {exc}",
        ))
    finally:
        writer.close()


def _drain_results(reader, messages):
    try:
        while True:
            messages.put(reader.recv())
    except EOFError:
        pass
    except Exception as exc:
        messages.put(exc)
    finally:
        try:
            reader.close()
        except Exception as exc:
            messages.put(exc)
        messages.put(None)


def execute_in_process(target, max_time, instance, model_name, start_time=None):
    start = perf_counter() if start_time is None else start_time
    result = ExecutionResult(
        instance["case_name"], model_name, None, PAVER.TERMINATION_ERROR, None, 0.0
    )
    reader = writer = process = receiver = None
    messages = Queue()
    timed_out = received = interrupted = False
    errors = []
    try:
        if not math.isfinite(max_time):
            raise ValueError("max_time must be finite.")
        deadline = start + max_time
        if perf_counter() >= deadline:
            timed_out = True
        else:
            reader, writer = multiprocessing.Pipe(duplex=False)
            process = multiprocessing.Process(
                target=_run_worker, args=(target, writer, max_time, instance, model_name),
            )
            process.start()
            writer.close()
            # A timed multiprocessing.Queue.get can still block on a partial
            # frame. Only this receiver blocks on IPC; the deadline owner never does.
            receiver = Thread(target=_drain_results, args=(reader, messages), daemon=True)
            receiver.start()
            while True:
                remaining = deadline - perf_counter()
                if remaining <= 0:
                    timed_out = True
                    break
                try:
                    message = messages.get(timeout=min(0.05, remaining))
                except Empty:
                    continue
                if message is None:
                    process.join(max(0.0, deadline - perf_counter()))
                    timed_out = process.is_alive()
                    break
                if isinstance(message, ExecutionResult):
                    result = message
                    received = True
                    if message.error_message:
                        errors.append(message.error_message)
                else:
                    errors.append(f"Invalid worker message: {message!r}")
    except KeyboardInterrupt:
        interrupted = True
        result.model_status = (PAVER.MODEL_STATUS_FEASIBLE
                               if result.objective_value is not None
                               else PAVER.MODEL_STATUS_NO_SOLUTION)
        result.termination_status = PAVER.TERMINATION_USER_INTERRUPT
        errors.append("Execution interrupted by user.")
    except Exception as exc:
        result.termination_status = PAVER.TERMINATION_ERROR
        errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        if process is not None:
            try:
                if process.pid is not None:
                    if process.is_alive():
                        process.terminate()
                    process.join(0.2)
                    if process.is_alive():
                        process.kill()
                        process.join(0.2)
                    if process.is_alive():
                        errors.append("Worker did not exit after kill.")
                    elif not timed_out and process.exitcode != 0:
                        errors.append(f"Worker exited with exit code {process.exitcode}.")
                process.close()
            except Exception as exc:
                errors.append(f"Worker cleanup failed: {type(exc).__name__}: {exc}")
        if writer is not None:
            try:
                writer.close()
            except Exception as exc:
                errors.append(f"Result writer cleanup failed: {type(exc).__name__}: {exc}")
        if receiver is not None and receiver.ident is not None:
            receiver.join(0.2)
            if receiver.is_alive():
                errors.append("Result receiver did not stop after worker exit.")
        elif reader is not None:
            try:
                reader.close()
            except Exception as exc:
                errors.append(f"Result reader cleanup failed: {type(exc).__name__}: {exc}")
        # Recover complete messages already drained at the deadline, never read
        # a potentially truncated IPC frame on the supervising thread.
        while True:
            try:
                message = messages.get_nowait()
            except Empty:
                break
            if isinstance(message, ExecutionResult):
                result = message
                received = True
                if message.error_message:
                    errors.append(message.error_message)
            elif message is not None:
                errors.append(f"Invalid worker message: {message!r}")
    if not received and not timed_out and not errors:
        errors.append("Worker exited without a result.")
    if received and result.termination_status == PAVER.TERMINATION_ERROR and not errors:
        errors.append("Worker reported Error without a diagnostic.")
    if errors and result.termination_status != PAVER.TERMINATION_USER_INTERRUPT:
        result.termination_status = PAVER.TERMINATION_ERROR
        result.model_status = (PAVER.MODEL_STATUS_FEASIBLE
                               if result.objective_value is not None
                               else PAVER.MODEL_STATUS_ERROR)
    if timed_out:
        result.model_status = (PAVER.MODEL_STATUS_FEASIBLE
                               if result.objective_value is not None
                               else PAVER.MODEL_STATUS_NO_SOLUTION)
        result.termination_status = PAVER.TERMINATION_TIME_LIMIT
    if interrupted:
        result.model_status = (PAVER.MODEL_STATUS_FEASIBLE
                               if result.objective_value is not None
                               else PAVER.MODEL_STATUS_NO_SOLUTION)
        result.termination_status = PAVER.TERMINATION_USER_INTERRUPT
    if errors:
        result.error_message = "; ".join(dict.fromkeys(errors))
    result.case_name = instance["case_name"]
    result.model_name = model_name
    result.total_time_s = perf_counter() - start
    return result
