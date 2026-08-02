import itertools

import numpy as np


def generate_positions_castro(bin_width, bin_height, item_width, item_height):
    # Generate positions on the x axis (X).
    x_positions = [x for x in range(bin_width)]

    # Generate positions on the y axis (Y).
    y_positions = [y for y in range(bin_height)]

    # Generate valid positions on the x axis (X_i).
    valid_x_positions = [x for x in x_positions if x <= bin_width - item_width]

    # Generate valid positions on the y axis (Y_i).
    valid_y_positions = [y for y in y_positions if y <= bin_height - item_height]

    return x_positions, y_positions, valid_x_positions, valid_y_positions


def generate_positions_no_height_limit(bin_width, bin_height, item_width, item_height):
    # TODO: evaluate whether this old slave helper should be removed.
    x_positions = [x for x in range(bin_width)]
    y_positions = [y for y in range(bin_height)]
    valid_x_positions = [x for x in x_positions if x <= bin_width - item_width]
    valid_y_positions = [y for y in y_positions if y <= bin_height]
    return x_positions, y_positions, valid_x_positions, valid_y_positions


def generate_master_model_positions(bin_height):
    # TODO: evaluate whether this old master helper should be removed.
    y_positions = [y for y in range(bin_height)]
    valid_y_positions = [y for y in y_positions if y <= bin_height]
    return valid_y_positions


def generate_positions_cid_garcia(bin_width, bin_height, item_width, item_height):
    positions = []

    for j in range(item_width, bin_width + 1):
        for horizontal_offset in range(bin_width):
            if (j + horizontal_offset) <= bin_width:
                for i in range(item_height, bin_height + 1):
                    for vertical_offset in range(bin_height):
                        if (vertical_offset + i) <= bin_height:
                            positions.append((j - item_width, i - item_height))

    return list(set(positions))


def create_c_matrix(bin_width, bin_height, positions, item_width, item_height, points):
    # Used by older models.
    num_positions = len(positions)
    num_points = bin_width * bin_height
    c_matrix = np.zeros((num_positions, num_points), dtype=int)

    for j, (x_start, y_start) in enumerate(positions):
        for dx in range(item_width):
            for dy in range(item_height):
                x = x_start + dx
                y = y_start + dy
                if 0 <= x < bin_width and 0 <= y < bin_height:
                    point_index = points.index((x, y))
                    c_matrix[j, point_index] = 1

    return c_matrix


def generate_positions_xym(bin_width, bin_height, item_width, item_height):
    # Improved Marcelo method.
    q_x = {
        i * item_width + j * item_height
        for i in range(bin_width // item_width + 1)
        for j in range((bin_width - i * item_width) // item_height + 1)
    }

    q_y = {
        i * item_width + j * item_height
        for i in range(bin_height // item_width + 1)
        for j in range((bin_height - i * item_width) // item_height + 1)
    }

    q_x |= {0, max(0, bin_width - item_width), max(0, bin_width - item_height)}
    q_y |= {0, max(0, bin_height - item_height), max(0, bin_height - item_width)}

    non_rotated_x = sorted(x for x in q_x if x + item_width <= bin_width)
    non_rotated_y = sorted(y for y in q_y if y + item_height <= bin_height)
    xy_x = set(itertools.product(non_rotated_x, non_rotated_y))

    if item_width != item_height:
        rotated_x = sorted(x for x in q_x if x + item_height <= bin_width)
        rotated_y = sorted(y for y in q_y if y + item_width <= bin_height)
        xy_y = set(itertools.product(rotated_x, rotated_y))
    else:
        xy_y = set()

    return xy_x, xy_y


def generate_positions_xym2(bin_width, bin_height, item_width, item_height):
    # Method precondition: normalized dimensions with bin_width >= bin_height and item_width >= item_height.
    # The orchestrator normalizes the instance before calling this function.
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
