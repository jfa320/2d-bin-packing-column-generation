import os
from PIL import Image, ImageDraw, ImageFont


COLOR_FONDO = "white"
COLOR_BIN = "black"
COLOR_REBANADA_BORDE = "green"
COLOR_REBANADA_RELLENO = (200, 255, 200, 140)
COLOR_REBANADA_TEXTO = (0, 100, 0)
COLOR_ITEM = "blue"
COLOR_ITEM_TEXTO = (0, 0, 180)
COLOR_EJE = (80, 80, 80)
COLOR_LEYENDA = (30, 30, 30)


def _medir_texto(draw, font, texto):
    izquierda, arriba, derecha, abajo = draw.textbbox((0, 0), texto, font=font)
    return derecha - izquierda, abajo - arriba


def _obtener_rectangulo_item(item, escala, origen_x, origen_y, height_bin):
    x1 = origen_x + int(item.get_position_x() * escala)
    y_model = item.get_position_y() + item.get_height()
    y1 = origen_y + int((height_bin - y_model) * escala)
    x2 = x1 + int(item.get_width() * escala)
    y2 = y1 + int(item.get_height() * escala)
    return x1, y1, x2, y2


def _ajustar_rectangulo(rectangulo, delta):
    x1, y1, x2, y2 = rectangulo
    return x1 + delta, y1 + delta, x2 - delta, y2 - delta


def _obtener_rectangulo_slice_(slice_, escala, origen_x, origen_y, height_bin):
    if not slice_.get_items():
        return None

    min_x = min(item.get_position_x() for item in slice_.get_items())
    min_y = min(item.get_position_y() for item in slice_.get_items())
    max_x = max(item.get_position_x() + item.get_width() for item in slice_.get_items())
    max_y = max(item.get_position_y() + item.get_height() for item in slice_.get_items())

    x1 = origen_x + int(min_x * escala)
    y1 = origen_y + int((height_bin - max_y) * escala)
    x2 = origen_x + int(max_x * escala)
    y2 = origen_y + int((height_bin - min_y) * escala)
    return x1, y1, x2, y2


def _obtener_cells_slice_(slice_):
    cells = set()
    for item in slice_.get_items():
        x0 = item.get_position_x()
        y0 = item.get_position_y()
        for dx in range(item.get_width()):
            for dy in range(item.get_height()):
                cells.add((x0 + dx, y0 + dy))
    return cells


def _obtener_rectangulo_celda(celda, escala, origen_x, origen_y, height_bin):
    x, y = celda
    x1 = origen_x + int(x * escala)
    y1 = origen_y + int((height_bin - y - 1) * escala)
    x2 = origen_x + int((x + 1) * escala)
    y2 = origen_y + int((height_bin - y) * escala)
    return x1, y1, x2, y2


def _dibujar_slice_(draw, font, slice_, indice_slice_, escala, origen_x, origen_y, height_bin):
    cells = _obtener_cells_slice_(slice_)
    if not cells:
        return

    for celda in cells:
        draw.rectangle(
            _obtener_rectangulo_celda(celda, escala, origen_x, origen_y, height_bin),
            fill=COLOR_REBANADA_RELLENO
        )

    for x, y in cells:
        x1, y1, x2, y2 = _obtener_rectangulo_celda((x, y), escala, origen_x, origen_y, height_bin)
        if (x, y + 1) not in cells:
            draw.line([(x1, y1), (x2, y1)], fill=COLOR_REBANADA_BORDE, width=2)
        if (x + 1, y) not in cells:
            draw.line([(x2, y1), (x2, y2)], fill=COLOR_REBANADA_BORDE, width=2)
        if (x, y - 1) not in cells:
            draw.line([(x1, y2), (x2, y2)], fill=COLOR_REBANADA_BORDE, width=2)
        if (x - 1, y) not in cells:
            draw.line([(x1, y1), (x1, y2)], fill=COLOR_REBANADA_BORDE, width=2)

    min_x = min(x for x, _ in cells)
    max_y = max(y for _, y in cells)
    label_x = origen_x + int(min_x * escala) + 4
    label_y = origen_y + int((height_bin - max_y - 1) * escala) + 4
    draw.text(
        (label_x, label_y),
        f"R{indice_slice_}",
        fill=COLOR_REBANADA_TEXTO,
        font=font
    )


def _dibujar_ejes(draw, font, origen_x, origen_y, width_bin_px, height_bin_px, bin_width, bin_height):
    x0 = origen_x
    y0 = origen_y + height_bin_px

    for x in range(bin_width + 1):
        x_px = origen_x + int(x * (width_bin_px / bin_width))
        draw.line([(x_px, y0), (x_px, y0 + 6)], fill=COLOR_EJE, width=1)
        texto_x = str(x)
        width_texto_x, _ = _medir_texto(draw, font, texto_x)
        draw.text((x_px - width_texto_x // 2, y0 + 8), texto_x, fill=COLOR_EJE, font=font)

    for y in range(bin_height + 1):
        y_px = origen_y + int(height_bin_px - y * (height_bin_px / bin_height))
        draw.line([(x0 - 6, y_px), (x0, y_px)], fill=COLOR_EJE, width=1)
        texto_y = str(y)
        width_texto_y, height_texto_y = _medir_texto(draw, font, texto_y)
        draw.text((x0 - 10 - width_texto_y, y_px - height_texto_y // 2), texto_y, fill=COLOR_EJE, font=font)

    draw.text((origen_x + width_bin_px + 10, y0 - 12), "x", fill=COLOR_EJE, font=font)
    draw.text((x0 - 14, origen_y - 16), "y", fill=COLOR_EJE, font=font)


def _construir_lineas_leyenda(bin_width, bin_height, item_width, item_height, total_items, physical_item_bound):
    return [
        f"Bin: {bin_width} x {bin_height} | Item base: {item_width} x {item_height}",
        f"Cantidad de items colocados: {total_items}",
        f"Cota fisica de items: {physical_item_bound}",
        "Bordes: bin negro, slice_ verde, item azul",
        "Labels: Rk = slice_ k | Ij.i-NR = item no rotated | Ij.i-R = item rotated"
    ]


def _dibujar_leyenda(draw, font, margen, inicio_y, line_spacing, lineas):

    for indice, linea in enumerate(lineas):
        draw.text(
            (margen, inicio_y + indice * line_spacing),
            linea,
            fill=COLOR_LEYENDA,
            font=font
        )


def export_bin_solution_to_png(bin_width, bin_height, item_width, item_height, physical_item_bound, active_slices, output_path, escala=40, margen=32):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    width_bin_px = int(bin_width * escala)
    height_bin_px = int(bin_height * escala)
    font = ImageFont.load_default()
    total_items = sum(len(slice_.get_items()) for slice_ in active_slices)

    lineas_leyenda = _construir_lineas_leyenda(
        bin_width,
        bin_height,
        item_width,
        item_height,
        total_items,
        physical_item_bound
    )

    imagen_aux = Image.new("RGBA", (1, 1), COLOR_FONDO)
    draw_aux = ImageDraw.Draw(imagen_aux)

    max_y_label = str(bin_height)
    width_y_label, _ = _medir_texto(draw_aux, font, max_y_label)
    _, height_x_label = _medir_texto(draw_aux, font, str(bin_width))
    width_leyenda = max(_medir_texto(draw_aux, font, linea)[0] for linea in lineas_leyenda)
    height_linea = max(_medir_texto(draw_aux, font, linea)[1] for linea in lineas_leyenda)
    line_spacing = height_linea + 6

    margen_izquierdo = max(margen, width_y_label + 18)
    margen_superior = max(margen, 20)
    margen_derecho = max(margen, 24)
    margen_inferior_ejes = 8 + height_x_label + 12
    footer_height = len(lineas_leyenda) * line_spacing + 12

    image_width = max(width_bin_px + margen_izquierdo + margen_derecho, width_leyenda + 2 * margen)
    image_height = height_bin_px + margen_superior + margen_inferior_ejes + footer_height

    image = Image.new("RGBA", (image_width, image_height), COLOR_FONDO)
    draw = ImageDraw.Draw(image)

    origen_x = margen_izquierdo
    origen_y = margen_superior

    rect_bin = [
        origen_x,
        origen_y,
        origen_x + width_bin_px,
        origen_y + height_bin_px
    ]
    draw.rectangle(rect_bin, outline=COLOR_BIN, width=3)
    _dibujar_ejes(draw, font, origen_x, origen_y, width_bin_px, height_bin_px, bin_width, bin_height)

    for indice_slice_, slice_ in enumerate(active_slices, start=1):
        _dibujar_slice_(draw, font, slice_, indice_slice_, escala, origen_x, origen_y, bin_height)

        for indice_item, item in enumerate(slice_.get_items(), start=1):
            rect_item = _obtener_rectangulo_item(item, escala, origen_x, origen_y, bin_height)
            rect_item_interno = _ajustar_rectangulo(rect_item, 0)
            draw.rectangle(rect_item_interno, outline=COLOR_ITEM, width=2)
            estado_rotacion = "R" if item.get_rotated() else "NR"
            draw.text(
                (rect_item_interno[0] + 4, rect_item_interno[1] + 16),
                f"I{indice_slice_}.{indice_item}-{estado_rotacion}",
                fill=COLOR_ITEM_TEXTO,
                font=font
            )

    _dibujar_leyenda(draw, font, margen, origen_y + height_bin_px + margen_inferior_ejes, line_spacing, lineas_leyenda)

    image.convert("RGB").save(output_path, format="PNG")
