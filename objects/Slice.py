from objects import Item

class Slice:
    _id_counter = 1

    @classmethod
    def reset_id_counter(cls):
        cls._id_counter = 1

    def __init__(self, height, width, items=None, item_start_points=None):
        self.set_id(Slice._id_counter)
        Slice._id_counter += 1
        self.set_height(height)
        self.set_width(width)
        self.set_items(items or [])
        self.set_item_start_points(item_start_points or [])
        if self.get_item_start_points() is None or self.get_item_start_points() == []:
            self.place_item_start_points()


    def place_item_start_points(self):
        for item in self.get_items():
            x = item.get_position_x()
            y = item.get_position_y()
            self.__item_start_points.append((x, y))

    def set_id(self, id):
        if isinstance(id, int) and id > 0:
            self.__id = id
        else:
            raise ValueError("id must be a positive integer.")

    def get_id(self):
        return self.__id

    def set_height(self, height):
        if isinstance(height, (int, float)) and height > 0:
            self.__height = height
        else:
            raise ValueError("height must be a positive number.")

    def get_height(self):
        return self.__height

    def set_width(self, width):
        if isinstance(width, (int, float)) and width > 0:
            self.__width = width
        else:
            raise ValueError("width must be a positive number.")

    def get_width(self):
        return self.__width

    def set_items(self, items):
        if not isinstance(items, list):
            raise TypeError("items must be a list.")
        self.__items = items

    def get_items(self):
        return self.__items
    
    def get_total_items(self):
        return len(self.__items)

    def contains_item(self, item):
        if not isinstance(item, Item):
            raise TypeError("item must be an Item instance.")
        return item in self.__items

    def set_item_start_points(self, positions):
        if not isinstance(positions, list):
            raise TypeError("occupied positions must be a list.")
        if not all(isinstance(pos, tuple) and len(pos) == 2 for pos in positions):
            raise ValueError("each position must be an (x, y) tuple.")
        self.__item_start_points = positions

    def get_item_start_points(self):
        return self.__item_start_points

    def _append_item(self, item, position=None):
        if not isinstance(item, Item):
            raise TypeError("item must be an Item instance.")
        self.__items.append(item)
        self.append_item_start_position(position)
    
    def append_item_start_position(self, position):
        if not isinstance(position, tuple) or len(position) != 2:
            raise ValueError("position must be an (x, y) tuple.")
        self.__item_start_points.append(position)
        
    def place_item(self, new_item, x, y):
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            raise ValueError("coordinates must be numbers.")
        
        if (x, y) in self.__item_start_points:
            raise ValueError("position is already occupied.")
        
        new_item.set_position_x(x)
        new_item.set_position_y(y)
        self._append_item(new_item, (x, y))
             
    def __repr__(self):
        return (f"Slice(id={self.get_id()}, height={self.get_height()}, width={self.get_width()}, "
            f"items={self.get_items()}, item_start_points={self.get_item_start_points()})")
