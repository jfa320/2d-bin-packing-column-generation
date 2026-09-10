class ConfigData:
    def __init__(
        self,
        bin_width=None,
        bin_height=None,
        item_width=None,
        item_height=None
    ):
        self._bin_width = None
        self._bin_height = None
        self._item_width = None
        self._item_height = None

        if bin_width is not None:
            self.set_bin_width(bin_width)
        if bin_height is not None:
            self.set_bin_height(bin_height)
        if item_width is not None:
            self.set_item_width(item_width)
        if item_height is not None:
            self.set_item_height(item_height)

    # ---------- BIN WIDTH ----------
    def get_bin_width(self):
        return self._bin_width

    def set_bin_width(self, value):
        if value <= 0:
            raise ValueError("bin_width must be greater than 0")
        self._bin_width = value

    # ---------- BIN HEIGHT ----------
    def get_bin_height(self):
        return self._bin_height

    def set_bin_height(self, value):
        if value <= 0:
            raise ValueError("bin_height must be greater than 0")
        self._bin_height = value

    # ---------- ITEM WIDTH ----------
    def get_item_width(self):
        return self._item_width

    def set_item_width(self, value):
        if value <= 0:
            raise ValueError("item_width must be greater than 0")
        self._item_width = value

    # ---------- ITEM HEIGHT ----------
    def get_item_height(self):
        return self._item_height

    def set_item_height(self, value):
        if value <= 0:
            raise ValueError("item_height must be greater than 0")
        self._item_height = value

    # ---------- UTIL ----------
    def is_complete(self):
        return all([
            self._bin_width is not None,
            self._bin_height is not None,
            self._item_width is not None,
            self._item_height is not None
        ])

    def __str__(self):
        return (
            f"ConfigData("
            f"bin_width={self._bin_width}, "
            f"bin_height={self._bin_height}, "
            f"item_width={self._item_width}, "
            f"item_height={self._item_height})"
        )
