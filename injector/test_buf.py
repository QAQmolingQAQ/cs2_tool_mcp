import ctypes, struct, json

data = struct.pack('<IIII', 0x43533254, 1, 27, 0) + b'{"id":1,"method":"ping"}'
print(f'data len: {len(data)}')

buf = ctypes.create_string_buffer(data)
print(f'string_buffer raw len: {len(buf.raw)}')
print(f'string_buffer content[:16]: {list(buf.raw[:16])}')

buf2_type = ctypes.c_ubyte * len(data)
buf2 = buf2_type.from_buffer_copy(data)
print(f'ubyte_array len: {len(buf2)}')
print(f'ubyte_array content[:16]: {list(buf2[:16])}')

# Also test Python 3.10's create_buffer_copy
print(f'has create_buffer_copy: {hasattr(ctypes, "create_buffer_copy")}')
