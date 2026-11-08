package com.example.aiworkflow.execution.application;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class ExecutionStateMachineTest {

    @Test
    void isLegal_givenDocumentedTransitions_allowsOnlyListedEdges() {
        assertThat(ExecutionStateMachine.isLegal("QUEUED", "RUNNING")).isTrue();
        assertThat(ExecutionStateMachine.isLegal("QUEUED", "CANCELLING")).isTrue();
        assertThat(ExecutionStateMachine.isLegal("RUNNING", "WAITING")).isTrue();
        assertThat(ExecutionStateMachine.isLegal("WAITING", "RUNNING")).isTrue();
        assertThat(ExecutionStateMachine.isLegal("WAITING", "SUCCEEDED")).isTrue();
        assertThat(ExecutionStateMachine.isLegal("WAITING", "FAILED")).isTrue();
        assertThat(ExecutionStateMachine.isLegal("WAITING", "CANCELLING")).isTrue();
        assertThat(ExecutionStateMachine.isLegal("CANCELLING", "CANCELLED")).isTrue();
        assertThat(ExecutionStateMachine.isLegal("SUCCEEDED", "RUNNING")).isFalse();
        assertThat(ExecutionStateMachine.isLegal("FAILED", "QUEUED")).isFalse();
        assertThat(ExecutionStateMachine.isTerminal("TIMED_OUT")).isTrue();
    }
}
