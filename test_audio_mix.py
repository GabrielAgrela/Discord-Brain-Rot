import audioop

def get_mixed(test_chunks):
    seconds = 10
    bytes_per_sec = 192000
    total_bytes = int(seconds * bytes_per_sec)
    total_bytes = (total_bytes // 4) * 4
    cutoff = 0
    mixed_buffer = bytearray(total_bytes)
    
    for user_id, chunks in test_chunks.items():
        user_buffer = bytearray(total_bytes)
        current_offset_bytes = 0
        
        for ts, audio in chunks:
            if ts >= cutoff:
                expected_offset = current_offset_bytes
                actual_offset_sec = ts - cutoff
                actual_offset_bytes = int(actual_offset_sec * bytes_per_sec)
                actual_offset_bytes = (actual_offset_bytes // 4) * 4
                
                if expected_offset > 0 and abs(actual_offset_bytes - expected_offset) < 19200:
                    offset_bytes = expected_offset
                else:
                    offset_bytes = actual_offset_bytes
                    
                end_bytes = offset_bytes + len(audio)
                
                if offset_bytes < 0:
                    audio = audio[-offset_bytes:]
                    offset_bytes = 0
                    
                if end_bytes > total_bytes:
                    trim = end_bytes - total_bytes
                    audio = audio[:-trim]
                    end_bytes = total_bytes
                    
                if len(audio) > 0 and offset_bytes < total_bytes:
                    user_buffer[offset_bytes:end_bytes] = audio
                    current_offset_bytes = end_bytes
        
        mixed_buffer = bytearray(audioop.add(mixed_buffer, user_buffer, 2))
        
    return mixed_buffer

# Test with mock data
chunks = {
    1: [(0.0, b'A' * 3840), (0.021, b'B' * 3840), (1.0, b'C' * 3840)],
    2: [(0.5, b'D' * 3840), (0.520, b'E' * 3840)]
}

res = get_mixed(chunks)
print(len(res))
# Look at first bytes
print(res[0:10])
