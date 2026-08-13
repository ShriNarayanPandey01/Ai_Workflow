package com.example.aiworkflow.execution.application;

import com.example.aiworkflow.execution.persistence.ExecutionEntity;
import com.example.aiworkflow.execution.persistence.ExecutionEventEntity;
import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@Component
public class ExecutionSseHub {

    private static final Logger log = LoggerFactory.getLogger(ExecutionSseHub.class);
    private final Map<UUID, CopyOnWriteArrayList<SseEmitter>> emitters = new ConcurrentHashMap<>();

    public SseEmitter subscribe(UUID runId) {
        SseEmitter emitter = new SseEmitter(0L);
        emitters.computeIfAbsent(runId, id -> new CopyOnWriteArrayList<>()).add(emitter);
        emitter.onCompletion(() -> remove(runId, emitter));
        emitter.onTimeout(() -> remove(runId, emitter));
        emitter.onError(ex -> remove(runId, emitter));
        return emitter;
    }

    public void sendReplay(SseEmitter emitter, List<ExecutionEventEntity> events) {
        for (ExecutionEventEntity event : events) {
            send(emitter, event);
        }
    }

    public void notify(ExecutionEventEntity event, ExecutionEntity run) {
        List<SseEmitter> list = emitters.get(event.getExecutionId());
        if (list == null) {
            return;
        }
        for (SseEmitter emitter : list) {
            send(emitter, event);
            if (ExecutionStateMachine.isTerminal(run.getStatus())) {
                emitter.complete();
            }
        }
    }

    @Scheduled(fixedDelay = 15000)
    public void heartbeat() {
        SseEmitter.SseEventBuilder ping = SseEmitter.event().comment("heartbeat");
        emitters.forEach((runId, list) -> {
            for (SseEmitter emitter : list) {
                try {
                    emitter.send(ping);
                } catch (IOException ex) {
                    remove(runId, emitter);
                }
            }
        });
    }

    private void send(SseEmitter emitter, ExecutionEventEntity event) {
        try {
            emitter.send(SseEmitter.event()
                    .id(Integer.toString(event.getSequence()))
                    .name(event.getEventType())
                    .data(event.getPayloadJson()));
        } catch (IOException ex) {
            log.debug("sse send failed run={}", event.getExecutionId());
            emitter.complete();
        }
    }

    private void remove(UUID runId, SseEmitter emitter) {
        List<SseEmitter> list = emitters.get(runId);
        if (list != null) {
            list.remove(emitter);
            if (list.isEmpty()) {
                emitters.remove(runId);
            }
        }
    }
}
