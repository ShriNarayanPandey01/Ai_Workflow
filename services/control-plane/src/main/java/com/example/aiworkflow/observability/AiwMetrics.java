package com.example.aiworkflow.observability;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.stereotype.Component;

@Component
public class AiwMetrics {

    private final Counter runsStarted;
    private final Counter outboxPublished;
    private final Counter ingestQueued;

    public AiwMetrics(MeterRegistry registry) {
        this.runsStarted = Counter.builder("aiw.runs.started").description("Runs started").register(registry);
        this.outboxPublished =
                Counter.builder("aiw.outbox.published").description("Outbox messages published").register(registry);
        this.ingestQueued =
                Counter.builder("aiw.ingest.queued").description("Document ingest commands queued").register(registry);
    }

    public void incrementRunsStarted() {
        runsStarted.increment();
    }

    public void incrementOutboxPublished() {
        outboxPublished.increment();
    }

    public void incrementIngestQueued() {
        ingestQueued.increment();
    }
}
