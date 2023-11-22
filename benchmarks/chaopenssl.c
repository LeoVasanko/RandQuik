#include <openssl/evp.h>
#include <stdio.h>
#include <string.h>

int main() {
    // Key and IV should be appropriately sized for ChaCha20
    unsigned char key[] = {
        0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,
        0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f,
        0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17,
        0x18, 0x19, 0x1a, 0x1b, 0x1c, 0x1d, 0x1e, 0x1f
    };
    unsigned char iv[] = {
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00
    };

    // Initialize context
    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    if (!ctx) {
        perror("EVP_CIPHER_CTX_new failed");
        return 1;
    }

    // Initialize the ChaCha20 cipher
    if (!EVP_EncryptInit_ex(ctx, EVP_chacha20(), NULL, key, iv)) {
        perror("EVP_EncryptInit_ex failed");
        EVP_CIPHER_CTX_free(ctx);
        return 1;
    }

    // Buffer for the keystream
    unsigned char keystream[1000000];
    memset(keystream, 0, sizeof(keystream));

    for (int i = 0; i < 1000; i++) {
        // Generate keystream
        int len;
        if (!EVP_EncryptUpdate(ctx, keystream, &len, keystream, sizeof keystream)) {
            perror("EVP_EncryptUpdate failed");
            EVP_CIPHER_CTX_free(ctx);
            return 1;
        }
    }
    // Clean up
    EVP_CIPHER_CTX_free(ctx);

    // Print the generated keystream
    for (int i = 0; i < 64; i++) {
        printf("%02x", keystream[i]);
    }
    printf("\n");

    return 0;
}
