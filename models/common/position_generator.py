import itertools


def generate_positions_xym(bin_width, bin_height, item_width, item_height):
    # Method precondition: normalized dimensions with bin_width >= bin_height and item_width >= item_height.
    # The orchestrator normalizes the instance before calling this function.

    # implementa el mismo principio de discretización espacial de los normal sets de Christofides y Whitlock,
    # adaptado a un problema mono-item con rotación.
    limit = bin_width - item_height

    q = {
        i * item_width + j * item_height
        for i in range(limit // item_width + 1)
        for j in range((limit - i * item_width) // item_height + 1)
    }

    non_rotated_x_positions = [q_value for q_value in q if q_value + item_width <= bin_width]
    non_rotated_y_positions = [q_value for q_value in q if q_value + item_height <= bin_height]
    xy_x = set(itertools.product(non_rotated_x_positions, non_rotated_y_positions))

    if item_width != item_height:
        rotated_x_positions = [q_value for q_value in q if q_value + item_height <= bin_width]
        rotated_y_positions = [q_value for q_value in q if q_value + item_width <= bin_height]
        xy_y = set(itertools.product(rotated_x_positions, rotated_y_positions))
    else:
        xy_y = set()

    return xy_x, xy_y
