package com.example.aiworkflow.messaging.rabbit;

import com.example.aiworkflow.messaging.MessagingNames;
import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.core.QueueBuilder;
import org.springframework.amqp.core.TopicExchange;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
@ConditionalOnProperty(prefix = "aiw.messaging", name = "enabled", havingValue = "true")
public class RabbitTopologyConfig {

    @Bean
    TopicExchange commandsExchange() {
        return new TopicExchange(MessagingNames.COMMANDS_EXCHANGE, true, false);
    }

    @Bean
    TopicExchange eventsExchange() {
        return new TopicExchange(MessagingNames.EVENTS_EXCHANGE, true, false);
    }

    @Bean
    TopicExchange deadLetterExchange() {
        return new TopicExchange(MessagingNames.DEAD_LETTER_EXCHANGE, true, false);
    }

    @Bean
    Queue executionCommandsQueue() {
        return QueueBuilder.durable(MessagingNames.EXECUTION_COMMANDS_QUEUE)
                .withArgument("x-dead-letter-exchange", MessagingNames.DEAD_LETTER_EXCHANGE)
                .build();
    }

    @Bean
    Queue ingestionCommandsQueue() {
        return QueueBuilder.durable(MessagingNames.INGESTION_COMMANDS_QUEUE)
                .withArgument("x-dead-letter-exchange", MessagingNames.DEAD_LETTER_EXCHANGE)
                .build();
    }

    @Bean
    Queue taskCommandsQueue() {
        return QueueBuilder.durable(MessagingNames.TASK_COMMANDS_QUEUE)
                .withArgument("x-dead-letter-exchange", MessagingNames.DEAD_LETTER_EXCHANGE)
                .build();
    }

    @Bean
    Queue controlEventsQueue() {
        return QueueBuilder.durable(MessagingNames.CONTROL_EVENTS_QUEUE)
                .withArgument("x-dead-letter-exchange", MessagingNames.DEAD_LETTER_EXCHANGE)
                .build();
    }

    @Bean
    Queue deadLetterQueue() {
        return QueueBuilder.durable(MessagingNames.DEAD_LETTER_QUEUE).build();
    }

    @Bean
    Binding executionCommandsBinding(Queue executionCommandsQueue, TopicExchange commandsExchange) {
        return BindingBuilder.bind(executionCommandsQueue)
                .to(commandsExchange)
                .with(MessagingNames.EXECUTION_COMMANDS_BINDING);
    }

    @Bean
    Binding ingestionCommandsBinding(Queue ingestionCommandsQueue, TopicExchange commandsExchange) {
        return BindingBuilder.bind(ingestionCommandsQueue)
                .to(commandsExchange)
                .with(MessagingNames.INGESTION_COMMANDS_BINDING);
    }

    @Bean
    Binding taskCommandsBinding(Queue taskCommandsQueue, TopicExchange commandsExchange) {
        return BindingBuilder.bind(taskCommandsQueue).to(commandsExchange).with(MessagingNames.TASK_COMMANDS_BINDING);
    }

    @Bean
    Binding controlEventsBinding(Queue controlEventsQueue, TopicExchange eventsExchange) {
        return BindingBuilder.bind(controlEventsQueue).to(eventsExchange).with(MessagingNames.CONTROL_EVENTS_BINDING);
    }

    @Bean
    Binding deadLetterBinding(Queue deadLetterQueue, TopicExchange deadLetterExchange) {
        return BindingBuilder.bind(deadLetterQueue).to(deadLetterExchange).with("#");
    }
}
