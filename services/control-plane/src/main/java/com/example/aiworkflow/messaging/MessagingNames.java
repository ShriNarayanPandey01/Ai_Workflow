package com.example.aiworkflow.messaging;

public final class MessagingNames {

    public static final String COMMANDS_EXCHANGE = "aiw.commands.v1";
    public static final String EVENTS_EXCHANGE = "aiw.events.v1";
    public static final String DEAD_LETTER_EXCHANGE = "aiw.dead.v1";
    public static final String EXECUTION_COMMANDS_QUEUE = "aiw.execution.commands.v1";
    public static final String INGESTION_COMMANDS_QUEUE = "aiw.ingestion.commands.v1";
    public static final String TASK_COMMANDS_QUEUE = "aiw.task.commands.v1";
    public static final String CONTROL_EVENTS_QUEUE = "aiw.control.events.v1";
    public static final String DEAD_LETTER_QUEUE = "aiw.dead.q.v1";
    public static final String EXECUTION_COMMANDS_BINDING = "execution.*.v1";
    public static final String INGESTION_COMMANDS_BINDING = "document.*.v1";
    public static final String TASK_COMMANDS_BINDING = "task.*.v1";
    public static final String CONTROL_EVENTS_BINDING = "#";
    public static final String CONSUMER_NAME = "control-plane";

    private MessagingNames() {}

    public static String routingKey(String messageType) {
        return messageType + ".v1";
    }
}
