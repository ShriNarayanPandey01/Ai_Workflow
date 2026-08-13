package com.example.aiworkflow.execution.application;

import java.util.Map;
import java.util.Set;

public final class ExecutionStateMachine {

    public static final Set<String> TERMINAL = Set.of("SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT");

    private static final Map<String, Set<String>> LEGAL = Map.of(
            "QUEUED", Set.of("RUNNING", "CANCELLED", "FAILED", "CANCELLING"),
            "RUNNING", Set.of("WAITING", "CANCELLING", "SUCCEEDED", "FAILED", "TIMED_OUT"),
            "WAITING", Set.of("RUNNING", "CANCELLING", "SUCCEEDED", "FAILED", "TIMED_OUT"),
            "CANCELLING", Set.of("CANCELLED"),
            "SUCCEEDED", Set.of(),
            "FAILED", Set.of(),
            "CANCELLED", Set.of(),
            "TIMED_OUT", Set.of());

    private ExecutionStateMachine() {}

    public static boolean isLegal(String from, String to) {
        if (from.equals(to)) {
            return true;
        }
        Set<String> next = LEGAL.get(from);
        return next != null && next.contains(to);
    }

    public static boolean isTerminal(String status) {
        return TERMINAL.contains(status);
    }
}
