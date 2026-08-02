import math
import multiprocessing
import time
from functools import lru_cache

from config import *


MODEL_NAME = "BacktrackingMonoitemExacto"


def _validate_dimensions(bin_width, bin_height, item_width, item_height):
    dimensions = [bin_width, bin_height, item_width, item_height]
    if not all(isinstance(value, int) and value > 0 for value in dimensions):
        raise ValueError("All dimensions must be positive integers.")
    if item_width > bin_width and item_width > bin_height:
        raise ValueError("The item does not fit in the bin in any orientation.")
    if item_height > bin_width and item_height > bin_height:
        raise ValueError("The item does not fit in the bin in any orientation.")


def _normalize_by_gcd(bin_width, bin_height, item_width, item_height):
    divisor = math.gcd(math.gcd(bin_width, bin_height), math.gcd(item_width, item_height))
    if divisor <= 1:
        return bin_width, bin_height, item_width, item_height, divisor
    return bin_width // divisor, bin_height // divisor, item_width // divisor, item_height // divisor, divisor


def _orientations(item_width, item_height, allow_rotation):
    orientations = [(item_width, item_height, False)]
    if allow_rotation and item_width != item_height:
        orientations.append((item_height, item_width, True))
    return orientations


def _overlap(rect_a, rect_b):
    ax, ay, aw, ah, _ = rect_a
    bx, by, bw, bh, _ = rect_b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _generate_regular_grid(bin_width, bin_height, orientation, quantity):
    item_width, item_height, rotated = orientation
    placements = []
    for y in range(0, bin_height - item_height + 1, item_height):
        for x in range(0, bin_width - item_width + 1, item_width):
            placements.append((x, y, item_width, item_height, rotated))
            if len(placements) == quantity:
                return placements
    return placements


def _can_place(rectangle, placed, bin_width, bin_height):
    x, y, width, height, _ = rectangle
    if x < 0 or y < 0 or x + width > bin_width or y + height > bin_height:
        return False
    return all(not _overlap(rectangle, existing) for existing in placed)


def _candidate_points(placed, bin_width, bin_height):
    xs = {0}
    ys = {0}
    for x, y, width, height, _ in placed:
        if x + width < bin_width:
            xs.add(x + width)
        if y + height < bin_height:
            ys.add(y + height)
    return sorted((x, y) for y in ys for x in xs)


def _search_packing(bin_width, bin_height, item_width, item_height, quantity, allow_rotation, deadline=None):
    orientations = _orientations(item_width, item_height, allow_rotation)
    area_bin = bin_width * bin_height
    area_item = item_width * item_height

    for orientation in orientations:
        if (bin_width // orientation[0]) * (bin_height // orientation[1]) >= quantity:
            return _generate_regular_grid(bin_width, bin_height, orientation, quantity)

    @lru_cache(maxsize=None)
    def backtracking(state):
        if deadline is not None and time.time() > deadline:
            raise TimeoutError("Time limit reached during backtracking.")

        placed = list(state)
        if len(placed) == quantity:
            return placed

        remaining = quantity - len(placed)
        free_area = area_bin - len(placed) * area_item
        if free_area // area_item < remaining:
            return None

        for x, y in _candidate_points(placed, bin_width, bin_height):
            for width, height, rotated in orientations:
                rectangle = (x, y, width, height, rotated)
                if not _can_place(rectangle, placed, bin_width, bin_height):
                    continue

                new_state = tuple(sorted(placed + [rectangle]))
                result = backtracking(new_state)
                if result is not None:
                    return result

        return None

    # In a bottom-left compacted solution, one item can always be fixed at the origin.
    for width, height, rotated in orientations:
        first_rectangle = (0, 0, width, height, rotated)
        if _can_place(first_rectangle, [], bin_width, bin_height):
            result = backtracking((first_rectangle,))
            if result is not None:
                return result

    return [] if quantity == 0 else None


def solve_exact_monoitem_2dbpp(bin_width, bin_height, item_width, item_height, allow_rotation=True, max_time=None):
    _validate_dimensions(bin_width, bin_height, item_width, item_height)

    original = (bin_width, bin_height, item_width, item_height)
    bin_width, bin_height, item_width, item_height, scale = _normalize_by_gcd(
        bin_width,
        bin_height,
        item_width,
        item_height
    )

    area_upper_bound = (bin_width * bin_height) // (item_width * item_height)
    deadline = None if max_time is None else time.time() + max_time

    for quantity in range(area_upper_bound, 0, -1):
        solution = _search_packing(
            bin_width,
            bin_height,
            item_width,
            item_height,
            quantity,
            allow_rotation,
            deadline
        )
        if solution is not None:
            scaled_solution = [
                {
                    "x": x * scale,
                    "y": y * scale,
                    "width": width * scale,
                    "height": height * scale,
                    "rotated": rotated,
                }
                for x, y, width, height, rotated in solution
            ]
            return {
                "bin_width": original[0],
                "bin_height": original[1],
                "item_width": original[2],
                "item_height": original[3],
                "allow_rotation": allow_rotation,
                "capacity": quantity,
                "area_upper_bound": area_upper_bound,
                "placements": scaled_solution,
            }

    return {
        "bin_width": original[0],
        "bin_height": original[1],
        "item_width": original[2],
        "item_height": original[3],
        "allow_rotation": allow_rotation,
        "capacity": 0,
        "area_upper_bound": area_upper_bound,
        "placements": [],
    }


def _solve_in_process(queue, max_time, instance):
    start_time = time.time()
    try:
        result = solve_exact_monoitem_2dbpp(
            instance["bin_width"],
            instance["bin_height"],
            instance["item_width"],
            instance["item_height"],
            allow_rotation=True,
            max_time=max_time
        )
        solver_time = time.time() - start_time
        print("-------------------------------------------")
        print("Exact monoitem backtracking without LP")
        print(f"Area upper bound: {result['area_upper_bound']}")
        print(f"Bin optimum: {result['capacity']}")
        print(f"Solve time: {solver_time:.2f} seconds")
        for index, item in enumerate(result["placements"], start=1):
            rotation_status = "R" if item["rotated"] else "NR"
            print(
                f"item {index}: x={item['x']}, y={item['y']}, "
                f"w={item['width']}, h={item['height']}, {rotation_status}"
            )

        queue.put({
            "modelStatus": "1",
            "solverStatus": "1",
            "objectiveValue": result["capacity"],
            "solverTime": solver_time,
        })
    except TimeoutError:
        queue.put({
            "modelStatus": "2",
            "solverStatus": "4",
            "objectiveValue": "n/a",
            "solverTime": time.time() - start_time,
        })
    except Exception as exc:
        print(f"Exact monoitem backtracking error: {exc}")
        queue.put({
            "modelStatus": "14",
            "solverStatus": "4",
            "objectiveValue": "n/a",
            "solverTime": time.time() - start_time,
        })


def execute_with_time_limit(max_time, instance=None):
    if instance is None:
        instance = get_instance(CASE_NAME)

    queue = multiprocessing.Queue()
    process = multiprocessing.Process(target=_solve_in_process, args=(queue, max_time, instance))
    process.start()
    process.join(max_time)

    if process.is_alive():
        process.terminate()
        process.join()
        print("The model exceeded the execution time limit.")
        return instance["case_name"], MODEL_NAME, "14", "4", "n/a", max_time

    if queue.empty():
        return instance["case_name"], MODEL_NAME, "14", "4", "n/a", max_time

    message = queue.get()
    return (
        instance["case_name"],
        MODEL_NAME,
        message["modelStatus"],
        message["solverStatus"],
        message["objectiveValue"],
        message["solverTime"],
    )


if __name__ == "__main__":
    print(execute_with_time_limit(1200))
