/* Actron QUE WallLink stream cipher: keep unsigned 32-bit state arithmetic. */
#include <stddef.h>
#include <stdint.h>

#define K0 UINT32_C(0xFE2D85CD)
#define K1 UINT32_C(0x043E9190)
#define K2 UINT32_C(0x2E0EA4A4)

/* Match the original Python signed-byte OR folding, including sign extension. */
static uint32_t extract32(const uint8_t *data) {
    uint32_t result = 0;
    for (size_t i = 0; i < 4; i++) {
        int32_t signed_byte = data[i] < 128 ? (int32_t)data[i] : (int32_t)data[i] - 256;
        result = (uint32_t)signed_byte | (result << 8);
    }
    return result;
}

static inline uint8_t next_bit(uint32_t *x, uint32_t *y, uint32_t *z) {
    uint32_t a = *x, b = *y, c = *z;
    const uint32_t fb0 = (a >> 6) ^ (a >> 31) ^ a ^ (a >> 4) ^ (a >> 2) ^ (a << 1);
    a = (a >> 1) | ((fb0 & 1u) << 31);
    const uint32_t fb1 = ((b >> 30) ^ (b >> 2)) & 1u;
    b = (b >> 1) | (fb1 << 30);
    const uint32_t zs = c >> 1;
    const uint32_t fb2 = (zs ^ (c >> 28)) & 1u;
    c = zs | (fb2 << 28);
    *x = a; *y = b; *z = c;
    return (uint8_t)((a ^ b ^ c) & 1u);
}

/* Encryption and decryption use the same XOR keystream. */
void walllink_xor(const uint8_t *seed, const uint8_t *input, uint8_t *output, size_t length) {
    uint32_t x = K0 ^ extract32(seed);
    uint32_t y = K1 ^ extract32(seed + 4);
    uint32_t z = K2 ^ extract32(seed + 8);
    for (size_t i = 0; i < length; i++) {
        uint8_t stream_byte = 0;
        for (unsigned bit = 0; bit < 8; bit++) {
            stream_byte = (uint8_t)(((stream_byte << 1) & 0xFEu) | next_bit(&x, &y, &z));
        }
        output[i] = input[i] ^ stream_byte;
    }
}
