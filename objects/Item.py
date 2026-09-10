class Item:
    _id_counter = 1
    
    def __init__(self, height, width, rotated=False, id=None, position_x=None, position_y=None):
        if id is None:
            self.set_id(Item._id_counter)
            Item._id_counter += 1
        else:
            self.set_id(id)
        self.set_height(height)
        self.set_width(width)
        self.set_rotated(rotated)
        self.set_position_x(position_x)
        self.set_position_y(position_y)

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
    
    def set_rotated(self, rotated):
        if isinstance(rotated, bool):
            self.__rotated = rotated
        else:
            raise ValueError("rotated must be a boolean.")

    def get_rotated(self):
        return self.__rotated
    
    def rotate(self):
        height_aux = self.get_height()
        self.__height = self.get_width()
        self.__width = height_aux
        self.__rotated = not self.get_rotated()

    def set_position_x(self, x):
        if isinstance(x, (int, float)) or x is None:
            self.__pos_x = x
        else:
            raise ValueError("position X must be a number or None.")

    def get_position_x(self):
        return self.__pos_x

    def set_position_y(self, y):
        if isinstance(y, (int, float)) or y is None:
            self.__pos_y = y
        else:
            raise ValueError("position Y must be a number or None.")

    def get_position_y(self):
        return self.__pos_y
    
    def get_position(self):
        return (self.get_position_x(), self.get_position_y())
    
    def set_position(self, x, y):
        self.set_position_x(x)
        self.set_position_y(y)

    def __repr__(self):
        return (f"Item(id={self.get_id()}, height={self.get_height()}, width={self.get_width()}, "
                f"rotated={self.get_rotated()}, x={self.get_position_x()}, y={self.get_position_y()})")
    
    def __eq__(self, other):
        return self.get_id() == other.get_id()
