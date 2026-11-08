# syntax=docker/dockerfile:1
FROM eclipse-temurin:21-jdk-alpine AS build
WORKDIR /workspace
COPY services/control-plane /workspace
RUN sed -i 's/\r$//' mvnw && chmod +x mvnw && ./mvnw -q -DskipTests package

FROM eclipse-temurin:21-jre-alpine
RUN addgroup -S aiw && adduser -S aiw -G aiw
WORKDIR /app
COPY --from=build /workspace/target/control-plane-0.1.0-SNAPSHOT.jar /app/app.jar
COPY contracts /contracts
USER aiw
EXPOSE 8080
ENV AIW_CONTRACTS_ROOT=/contracts
ENTRYPOINT ["java","-jar","/app/app.jar"]
