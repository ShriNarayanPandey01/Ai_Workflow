---
trigger: glob
globs: "services/control-plane/**"
description: Java/Spring Boot production standards (applies strictly and only to services/control-plane)
---

# Java Production Rules — Control Plane

> [!IMPORTANT]
> **Strict Scope:** This rule applies **ONLY** to Java/Spring Boot code within `services/control-plane/**`.  
> **DO NOT** apply these rules to the Python execution engine (`services/execution-engine`), rag services, or frontend code.

---

## 1. Spring Boot Architecture

- **Controllers:** HTTP only — request validation, DTO mapping, status codes. No business logic. Return DTOs (Java records), never JPA entities.
- **Services:** All business logic. `@Transactional` lives here. Accept/return DTOs or domain objects, not entities across API boundaries.
- **Repositories:** Spring Data interfaces. Custom queries use `@Query` JPQL (not native SQL unless specifically justified).
- **Dependency Injection:** Constructor injection only (`@RequiredArgsConstructor`). Injected fields: `private final`.
- **DTOs:** DTOs are Java records. Validate in compact constructors or with Jakarta validation annotations (`@NotNull`, `@NotBlank`, etc.).

```java
// BAD — entity leaked, logic in controller
@GetMapping("/{id}")
public User get(@PathVariable Long id) { return userRepo.findById(id).orElseThrow(); }

// GOOD
@GetMapping("/{id}")
public UserResponse get(@PathVariable Long id) { return userService.getById(id); }
```

---

## 2. Maven Standards

- Use `spring-boot-starter-parent` BOM. Never hardcode versions for BOM-managed dependencies.
- Explicit `<scope>` for `test` / `provided`. Group dependencies logically: starters, domain libraries, test libraries.
- Target **Java 21**. UTF-8 encoding. Surefire = unit tests, Failsafe = integration tests.

---

## 3. Error Handling

- Domain exceptions extend `DomainException` (`RuntimeException`). Include entity ID, operation name, and a machine-readable error code.
- `@RestControllerAdvice` maps domain exceptions to RFC 7807 `ProblemDetail`.
- Catch checked exceptions at the service boundary; wrap in domain exceptions (`cause` preserved).
- Never catch or throw generic `Exception` / `RuntimeException`.

---

## 4. Asynchronous Execution

- `CompletableFuture` with a **custom executor** for I/O — never the common `ForkJoinPool`.
- Chain with `thenApply` / `thenCompose`. Never `.get()` / `.join()` on request threads.
- `@Async` requires a configured `ThreadPoolTaskExecutor` bean.
- Handle failures in the chain: `exceptionally()` or equivalent — do not swallow errors.

---

## 5. Testing Standards

- **Unit Tests:** `@ExtendWith(MockitoExtension.class)`. Mock external boundaries and repositories only.
- **Naming Convention:** `methodName_givenCondition_expectedResult`.
- Assert behavior and return values, not mock interaction counts (unless interaction verification is the contract).
- **Integration Tests:** `@SpringBootTest` + Testcontainers. Shared fixtures via builders.

---

## 6. Documentation & Code Style

- Javadoc on public types and methods: explain **why** and **when**, not a mechanical restatement of the method signature.
- `@param`, `@return`, `@throws` with real semantic meaning.
- Inline comments only for complex business rules.

---

## 7. Refactoring & Code Quality

- Extract methods named for purpose, not implementation (e.g., `applyTenantQuota`, not `loopAndSum`).
- Use generics to remove duplication; bounded wildcards on input parameters.
- Replace `instanceof` branching chains with polymorphism.
- Abstract shared behavior only when **3 or more** classes share it.

---

## 8. Performance Optimization

- `@Cacheable` for read-heavy data; `@CacheEvict` on mutations; configure explicit TTLs.
- `FetchType.LAZY` by default on JPA relations. Use `JOIN FETCH` or `@EntityGraph` for relations actually needed in queries.
- Streams for transformations, not side effects. Prefer `.toList()` over `Collectors.toList()`.
- Always paginate with `Pageable`. Never load unbounded collections into memory.
- `parallelStream()` only for CPU-bound computations with **10,000+** elements.
