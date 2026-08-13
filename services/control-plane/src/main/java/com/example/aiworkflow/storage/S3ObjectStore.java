package com.example.aiworkflow.storage;

import com.example.aiworkflow.config.AiwProperties;
import java.net.URI;
import java.time.Clock;
import java.time.Duration;
import java.util.Map;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.s3.S3Configuration;
import software.amazon.awssdk.services.s3.model.GetObjectRequest;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;
import software.amazon.awssdk.services.s3.presigner.model.PresignedGetObjectRequest;
import software.amazon.awssdk.services.s3.presigner.model.PresignedPutObjectRequest;

public class S3ObjectStore implements ObjectStore {

    private final AiwProperties.Storage storage;
    private final S3Presigner presigner;
    private final Clock clock;

    public S3ObjectStore(AiwProperties.Storage storage, Clock clock) {
        this.storage = storage;
        this.clock = clock;
        this.presigner = S3Presigner.builder()
                .endpointOverride(URI.create(storage.endpoint()))
                .region(Region.of(storage.region()))
                .credentialsProvider(StaticCredentialsProvider.create(
                        AwsBasicCredentials.create(storage.accessKey(), storage.secretKey())))
                .serviceConfiguration(S3Configuration.builder().pathStyleAccessEnabled(storage.pathStyle()).build())
                .build();
    }

    @Override
    public PresignedObject presignPut(String objectKey, String mediaType, Duration ttl) {
        PutObjectRequest put = PutObjectRequest.builder()
                .bucket(storage.bucket())
                .key(objectKey)
                .contentType(mediaType)
                .build();
        PresignedPutObjectRequest signed =
                presigner.presignPutObject(r -> r.signatureDuration(ttl).putObjectRequest(put));
        return new PresignedObject(signed.url().toString(), Map.of("Content-Type", mediaType), clock.instant().plus(ttl));
    }

    @Override
    public PresignedObject presignGet(String objectKey, Duration ttl) {
        GetObjectRequest get =
                GetObjectRequest.builder().bucket(storage.bucket()).key(objectKey).build();
        PresignedGetObjectRequest signed =
                presigner.presignGetObject(r -> r.signatureDuration(ttl).getObjectRequest(get));
        return new PresignedObject(signed.url().toString(), Map.of(), clock.instant().plus(ttl));
    }
}
