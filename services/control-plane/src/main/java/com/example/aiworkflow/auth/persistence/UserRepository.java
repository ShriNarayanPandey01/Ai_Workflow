package com.example.aiworkflow.auth.persistence;

import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface UserRepository extends JpaRepository<UserEntity, UUID> {

    Optional<UserEntity> findByEmailNormalized(String emailNormalized);

    boolean existsByEmailNormalized(String emailNormalized);
}
