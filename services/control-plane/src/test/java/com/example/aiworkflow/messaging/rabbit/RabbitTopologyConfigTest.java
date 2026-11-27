package com.example.aiworkflow.messaging.rabbit;

import static org.assertj.core.api.Assertions.assertThat;

import com.example.aiworkflow.messaging.MessagingNames;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.core.Queue;

class RabbitTopologyConfigTest {
    @Test
    void sharedQueuesUseTheSameDeadLetterArgumentsAsTheWorkers() {
        var topology = new RabbitTopologyConfig();
        for (Queue queue : new Queue[] {
            topology.executionCommandsQueue(), topology.taskCommandsQueue(),
            topology.ingestionCommandsQueue(), topology.controlEventsQueue()
        }) {
            assertThat(queue.getArguments())
                    .containsEntry("x-dead-letter-exchange", MessagingNames.DEAD_LETTER_EXCHANGE)
                    .containsEntry("x-dead-letter-routing-key", "rejected");
        }
    }
}
