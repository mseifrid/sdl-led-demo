"""Minimal SSD1306 OLED driver (I2C) for MicroPython, based on framebuf."""

import framebuf

_CMDS = (
    0xAE,              # display off
    0x20, 0x00,        # horizontal addressing
    0x40,              # start line 0
    0xA1,              # segment remap
    0xA8, 63,          # multiplex ratio (height - 1)
    0xC8,              # COM scan direction
    0xD3, 0x00,        # display offset
    0xDA, 0x12,        # COM pins
    0xD5, 0x80,        # clock divide
    0xD9, 0xF1,        # pre-charge
    0xDB, 0x30,        # VCOM detect
    0x81, 0xFF,        # contrast
    0xA4,              # follow RAM
    0xA6,              # normal (not inverted)
    0x8D, 0x14,        # charge pump on
    0xAF,              # display on
)


class SSD1306_I2C(framebuf.FrameBuffer):
    def __init__(self, width, height, i2c, addr=0x3C):
        self.width, self.height = width, height
        self.i2c, self.addr = i2c, addr
        self.pages = height // 8
        self.buffer = bytearray(self.pages * width)
        super().__init__(self.buffer, width, height, framebuf.MONO_VLSB)
        for c in _CMDS:
            self.cmd(c)
        self.fill(0)
        self.show()

    def cmd(self, c):
        self.i2c.writeto(self.addr, bytes((0x80, c)))

    def show(self):
        for c in (0x21, 0, self.width - 1, 0x22, 0, self.pages - 1):
            self.cmd(c)
        self.i2c.writeto(self.addr, b"\x40" + self.buffer)
