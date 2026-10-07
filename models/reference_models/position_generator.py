"""Position generators and coverage matrix used by the reference models."""

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
