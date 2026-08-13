package com.example.aiworkflow.trigger.application;

import java.time.Instant;
import java.util.UUID;
import org.quartz.DisallowConcurrentExecution;
import org.quartz.Job;
import org.quartz.JobExecutionContext;
import org.springframework.stereotype.Component;

@Component
@DisallowConcurrentExecution
public class ScheduleTriggerJob implements Job {

    private final TriggerService triggers;

    public ScheduleTriggerJob(TriggerService triggers) {
        this.triggers = triggers;
    }

    @Override
    public void execute(JobExecutionContext context) {
        String triggerId = context.getMergedJobDataMap().getString("triggerId");
        Instant fireTime = context.getScheduledFireTime().toInstant();
        triggers.dispatchScheduled(UUID.fromString(triggerId), fireTime);
    }
}
