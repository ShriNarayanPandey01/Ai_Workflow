package com.example.aiworkflow.credential.crypto;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.UUID;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.stereotype.Component;

@Component
public class AesGcmCrypter {

    private static final int NONCE_LENGTH = 12;
    private static final int TAG_BITS = 128;
    private final SecureRandom random = new SecureRandom();

    public record Sealed(byte[] ciphertext, byte[] nonce) {}

    public byte[] keyFromSecret(String kek) {
        try {
            return MessageDigest.getInstance("SHA-256").digest(kek.getBytes(StandardCharsets.UTF_8));
        } catch (GeneralSecurityException ex) {
            throw new IllegalStateException("Unable to derive credential key", ex);
        }
    }

    public byte[] aad(UUID id, UUID workspaceId, UUID projectId, String type) {
        return (id + "|" + workspaceId + "|" + projectId + "|" + type).getBytes(StandardCharsets.UTF_8);
    }

    public Sealed encrypt(byte[] key, byte[] plaintext, byte[] aad) {
        byte[] nonce = new byte[NONCE_LENGTH];
        random.nextBytes(nonce);
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, new SecretKeySpec(key, "AES"), new GCMParameterSpec(TAG_BITS, nonce));
            cipher.updateAAD(aad);
            byte[] ciphertext = cipher.doFinal(plaintext);
            return new Sealed(ciphertext, nonce);
        } catch (GeneralSecurityException ex) {
            throw new IllegalStateException("Credential encryption failed", ex);
        }
    }

    public byte[] decrypt(byte[] key, byte[] ciphertext, byte[] nonce, byte[] aad) {
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, new SecretKeySpec(key, "AES"), new GCMParameterSpec(TAG_BITS, nonce));
            cipher.updateAAD(aad);
            return cipher.doFinal(ciphertext);
        } catch (GeneralSecurityException ex) {
            throw new IllegalStateException("Credential decryption failed", ex);
        } finally {
            Arrays.fill(key, (byte) 0);
        }
    }

    public static String mask(String secret) {
        if (secret == null || secret.isBlank()) {
            return "****";
        }
        String trimmed = secret.trim();
        if (trimmed.length() <= 4) {
            return "****";
        }
        return "****" + trimmed.substring(trimmed.length() - 4);
    }

    public static byte[] concat(byte[] a, byte[] b) {
        return ByteBuffer.allocate(a.length + b.length).put(a).put(b).array();
    }
}
