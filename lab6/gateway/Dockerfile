# API Gateway (LAB4): budowanie wieloetapowe. Etap 1 kompiluje Mavenem, etap 2 zawiera tylko JRE i gotowy jar.
FROM maven:3.9.11-eclipse-temurin-21 AS build

WORKDIR /workspace
# Najpierw sam pom.xml i pobranie zależności: zmiana kodu nie wymusza ponownego pobierania z internetu.
COPY pom.xml ./
RUN mvn -B -DskipTests dependency:go-offline
COPY src ./src
RUN mvn -B -DskipTests package

FROM eclipse-temurin:21-jre-alpine

WORKDIR /app
COPY --from=build /workspace/target/api-gateway.jar /app/app.jar

RUN addgroup -S app && adduser -S app -G app
USER app

# Adres nasłuchiwania (SERVER_ADDRESS=0.0.0.0) i port (GATEWAY_PORT) przychodzą z compose.yaml.
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
