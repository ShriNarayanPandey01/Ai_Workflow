package com.example.aiworkflow.credential.crypto;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.charset.StandardCharsets;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class AesGcmCrypterTest {

    private final AesGcmCrypter crypter = new AesGcmCrypter();

    @Test
    void encrypt_givenMatchingAad_decryptsPlaintext() {
        byte[] key = crypter.keyFromSecret("development-only-credential-kek-must-be-32b");
        UUID id = UUID.randomUUID();
        byte[] aad = crypter.aad(id, UUID.randomUUID(), UUID.randomUUID(), "openai_compatible");
        AesGcmCrypter.Sealed sealed = crypter.encrypt(key, "secret-value".getBytes(StandardCharsets.UTF_8), aad);
        byte[] plain = crypter.decrypt(crypter.keyFromSecret("development-only-credential-kek-must-be-32b"), sealed.ciphertext(), sealed.nonce(), aad);
        assertThat(new String(plain, StandardCharsets.UTF_8)).isEqualTo("secret-value");
        assertThat(AesGcmCrypter.mask("sk-abcdef")).isEqualTo("****cdef");
    }

    @Test
    void decrypt_givenMismatchedAad_fails() {
        byte[] key = crypter.keyFromSecret("development-only-credential-kek-must-be-32b");
        UUID id = UUID.randomUUID();
        byte[] aad = crypter.aad(id, UUID.randomUUID(), UUID.randomUUID(), "openai_compatible");
        AesGcmCrypter.Sealed sealed = crypter.encrypt(key, "secret-value".getBytes(StandardCharsets.UTF_8), aad);
        byte[] other = crypter.aad(id, UUID.randomUUID(), UUID.randomUUID(), "openai_compatible");
        assertThatThrownBy(() -> crypter.decrypt(
                        crypter.keyFromSecret("development-only-credential-kek-must-be-32b"),
                        sealed.ciphertext(),
                        sealed.nonce(),
                        other))
                .isInstanceOf(IllegalStateException.class);
    }
}
