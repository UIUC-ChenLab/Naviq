import random

# Configuration
total_bytes = 2048        # 2KB total BRAM size
word_width_bytes = 2      # 32-bit data width (4 bytes)
filename = "random_bram.mem"

# Calculate how many words (lines) we need
num_words = total_bytes // word_width_bytes

with open(filename, "w") as f:
    for _ in range(num_words):
        # Generate a random number up to the max value for our word width
        val = random.randint(0, (1 << (word_width_bytes * 8)) - 1)
        # Format as uppercase Hex, padded with leading zeros (8 characters for 32-bit)
        f.write(f"{val:08X}\n")

print(f"Success! Generated {filename} with {num_words} words.")