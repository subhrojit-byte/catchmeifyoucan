package catchmeifyoucan.service;

import catchmeifyoucan.dto.FraudScenarioResponse;
import tools.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Duration;
import java.util.ArrayDeque;
import java.util.List;
import java.util.Optional;
import java.util.Queue;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.AbstractExecutorService;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.LongSupplier;

import static catchmeifyoucan.service.FraudsterRunCredentialService.OPERATION;
import static catchmeifyoucan.service.FraudsterRunCredentialService.ROLE;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class AgentRunLifecycleTest {
    private final FraudsterRunCredentialService credentials = new FraudsterRunCredentialService(
            new SecureRandom(), Clock.systemUTC(), Duration.ofMinutes(5));

    @Test
    void inferenceUsesDefaultFraudsterAndConfiguredCompatibleInvestigatorCheckpoint() throws Exception {
        var executor = new QueuedExecutor();
        AtomicReference<List<String>> command = new AtomicReference<>();
        FraudScenarioService scenarios = mock(FraudScenarioService.class);
        FraudScenarioResponse scenario = mock(FraudScenarioResponse.class);
        when(scenario.getStatus()).thenReturn("ACTIVE");
        when(scenarios.findScenario(88L)).thenReturn(Optional.of(scenario));
        Path runner = Path.of("rl-agents", "run_learned_episode.py").toAbsolutePath().normalize();
        assertTrue(Files.isRegularFile(runner));

        AgentRunService service = new AgentRunService(
                scenarios, credentials, new ObjectMapper(), "python", runner.toString(), "",
                "investigator-managed-run-29b5f61c-d747-46b6-ae22-46a141ac5cb9.json",
                60, 60, executor, builder -> {
                    command.set(List.copyOf(builder.command()));
                    return process(episodeResult(), true);
                });

        var run = service.start(88L);
        executor.runNext();

        assertEquals("COMPLETED", service.get(run.runId()).status());
        int fraudsterIndex = command.get().indexOf("--fraudster-checkpoint");
        int investigatorIndex = command.get().indexOf("--investigator-checkpoint");
        assertTrue(fraudsterIndex > 0);
        assertTrue(investigatorIndex > 0);
        assertEquals(runner.getParent().resolve(
                "fraudster-trained-run-120d17a1-5012-45c9-89a8-97b4dab1a5fb.json").toString(),
                command.get().get(fraudsterIndex + 1));
        assertEquals(runner.getParent().resolve(
                "investigator-managed-run-29b5f61c-d747-46b6-ae22-46a141ac5cb9.json").toString(),
                command.get().get(investigatorIndex + 1));
        service.shutdown();
    }

    @Test
    void humanFraudsterMatchLoadsOnlyInvestigatorAndDoesNotIssuePrivateKnowledgeGrant() throws Exception {
        var executor = new QueuedExecutor();
        AtomicReference<List<String>> command = new AtomicReference<>();
        AtomicReference<String> token = new AtomicReference<>();
        FraudScenarioService scenarios = mock(FraudScenarioService.class);
        FraudScenarioResponse scenario = mock(FraudScenarioResponse.class);
        when(scenario.getStatus()).thenReturn("ACTIVE");
        when(scenarios.findScenario(89L)).thenReturn(Optional.of(scenario));
        Path runner = Path.of("rl-agents", "run_learned_episode.py").toAbsolutePath().normalize();
        AgentRunService service = new AgentRunService(
                scenarios, credentials, new ObjectMapper(), "python", runner.toString(), "", "",
                60, 60, executor, builder -> {
                    command.set(List.copyOf(builder.command()));
                    token.set(builder.environment().get(FraudsterRunCredentialService.ENVIRONMENT_VARIABLE));
                    return process(episodeResult(), true);
                });

        var run = service.startHumanFraudsterMatch(89L);
        executor.runNext();

        assertEquals("COMPLETED", service.get(run.runId()).status());
        assertTrue(command.get().contains("--human-fraudster"));
        assertFalse(command.get().contains("--fraudster-checkpoint"));
        assertFalse(command.get().contains("--pause-between-rounds"));
        int investigatorIndex = command.get().indexOf("--investigator-checkpoint");
        assertTrue(investigatorIndex > 0);
        assertTrue(command.get().get(investigatorIndex + 1).endsWith("investigator-trained-fresh-20261025.json"));
        assertNull(token.get());
        service.shutdown();
    }

    @Test
    void heuristicSearchUsesDedicatedRunnerWithoutCheckpointsOrPrivateCredential() throws Exception {
        var executor = new QueuedExecutor();
        AtomicReference<List<String>> command = new AtomicReference<>();
        AtomicReference<String> credential = new AtomicReference<>();
        AtomicReference<String> runScope = new AtomicReference<>();
        FraudScenarioService scenarios = mock(FraudScenarioService.class);
        FraudScenarioResponse scenario = mock(FraudScenarioResponse.class);
        when(scenario.getStatus()).thenReturn("ACTIVE");
        when(scenarios.findScenario(90L)).thenReturn(Optional.of(scenario));
        Path directory = Files.createTempDirectory("heuristic-run-test");
        Path learnedRunner = Files.createFile(directory.resolve("run_learned_episode.py"));
        Path heuristicRunner = Files.createFile(directory.resolve("run_heuristic_episode.py"));
        AgentRunService service = new AgentRunService(
                scenarios, credentials, new ObjectMapper(), "python", learnedRunner.toString(),
                "missing-fraudster.json", "missing-investigator.json", 60, 60, executor, builder -> {
                    command.set(List.copyOf(builder.command()));
                    credential.set(builder.environment().get(FraudsterRunCredentialService.ENVIRONMENT_VARIABLE));
                    runScope.set(builder.environment().get(FraudsterRunCredentialService.RUN_ID_ENVIRONMENT_VARIABLE));
                    return process(episodeResult(), true);
                });

        var run = service.startHeuristicSearch(90L);
        executor.runNext();

        assertEquals("COMPLETED", service.get(run.runId()).status());
        assertEquals(heuristicRunner.toAbsolutePath().normalize().toString(), command.get().get(1));
        assertFalse(command.get().contains("--fraudster-checkpoint"));
        assertFalse(command.get().contains("--investigator-checkpoint"));
        assertFalse(command.get().contains("--train-fraudster"));
        assertFalse(command.get().contains("--train-investigator"));
        assertNull(credential.get());
        assertNull(runScope.get());
        service.shutdown();
    }

    @Test
    void normalCompletionRevokesCredentialAndCleansUp() throws Exception {
        var executor = new QueuedExecutor();
        AtomicReference<String> token = new AtomicReference<>();
        AgentRunService service = service(executor, builder -> {
            token.set(builder.environment().get(FraudsterRunCredentialService.ENVIRONMENT_VARIABLE));
            return process(episodeResult(), true);
        }, 7L);

        var run = service.start(7L);
        executor.runNext();

        assertEquals("COMPLETED", service.get(run.runId()).status());
        assertFalse(authorized(token.get(), 7L, run.runId()));
        service.shutdown();
    }

    @Test
    void managedFraudsterTrainingUsesScopedCredentialAndFreshRunSpecificOutputs() throws Exception {
        var executor = new QueuedExecutor();
        AtomicReference<String> token = new AtomicReference<>();
        AtomicReference<String> runScope = new AtomicReference<>();
        AtomicReference<List<String>> command = new AtomicReference<>();
        AgentRunService service = service(executor, builder -> {
            token.set(builder.environment().get(FraudsterRunCredentialService.ENVIRONMENT_VARIABLE));
            runScope.set(builder.environment().get(FraudsterRunCredentialService.RUN_ID_ENVIRONMENT_VARIABLE));
            assertTrue(authorized(token.get(), 26L, runScope.get()));
            assertFalse(authorized(token.get(), 27L, runScope.get()));
            command.set(List.copyOf(builder.command()));
            int fraudsterOutputIndex = command.get().indexOf("--fraudster-output-checkpoint");
            int investigatorOutputIndex = command.get().indexOf("--investigator-output-checkpoint");
            String fraudsterOutput = command.get().get(fraudsterOutputIndex + 1);
            String investigatorOutput = command.get().get(investigatorOutputIndex + 1);
            Files.writeString(Path.of(fraudsterOutput), "trained");
            Files.writeString(Path.of(investigatorOutput), "trained");
            String trainingResult = "CATCHME_AGENT_EVENT {\"event_type\":\"training_result\","
                    + "\"scenario_id\":26,\"episode_count\":1,\"episode_completed\":true,"
                    + "\"fraudster_transition_count\":1,\"fraudster_training_steps\":1,"
                    + "\"fraudster_checkpoint\":" + new ObjectMapper().writeValueAsString(fraudsterOutput) + ","
                    + "\"investigator_checkpoint\":" + new ObjectMapper().writeValueAsString(investigatorOutput) + "}\n";
            return process((trainingResult + new String(episodeResult(), StandardCharsets.UTF_8))
                    .getBytes(StandardCharsets.UTF_8), true);
        }, 26L);

        var run = service.startFraudsterTraining(26L);
        executor.runNext();

        assertEquals("COMPLETED", service.get(run.runId()).status(), service.get(run.runId()).message());
        assertTrue(command.get().contains("--train-fraudster"));
        assertTrue(command.get().contains("--initialize-fresh"));
        assertFalse(command.get().contains("--fraudster-checkpoint"));
        assertFalse(command.get().contains("--investigator-checkpoint"));
        int fraudsterOutputIndex = command.get().indexOf("--fraudster-output-checkpoint");
        int investigatorOutputIndex = command.get().indexOf("--investigator-output-checkpoint");
        assertTrue(fraudsterOutputIndex > 0);
        assertTrue(investigatorOutputIndex > 0);
        String fraudsterOutput = command.get().get(fraudsterOutputIndex + 1);
        String investigatorOutput = command.get().get(investigatorOutputIndex + 1);
        assertTrue(fraudsterOutput.contains(run.runId()));
        assertTrue(investigatorOutput.contains(run.runId()));
        assertNotEquals(fraudsterOutput, investigatorOutput);
        assertTrue(fraudsterOutput.endsWith(".json"));
        assertTrue(investigatorOutput.endsWith(".json"));
        assertFalse(authorized(token.get(), 27L, run.runId()));
        assertFalse(authorized(token.get(), 26L, run.runId()));
        service.shutdown();
    }

    @Test
    void managedInvestigatorTrainingUsesScenarioCredentialAndRunSpecificCheckpoint() throws Exception {
        var executor = new QueuedExecutor();
        AtomicReference<String> token = new AtomicReference<>();
        AtomicReference<List<String>> command = new AtomicReference<>();
        AgentRunService service = service(executor, builder -> {
            token.set(builder.environment().get(FraudsterRunCredentialService.ENVIRONMENT_VARIABLE));
            String runId = builder.environment().get(FraudsterRunCredentialService.RUN_ID_ENVIRONMENT_VARIABLE);
            assertTrue(authorized(token.get(), 26L, runId));
            assertFalse(authorized(token.get(), 27L, runId));
            command.set(List.copyOf(builder.command()));
            int outputIndex = command.get().indexOf("--investigator-output-checkpoint");
            String output = command.get().get(outputIndex + 1);
            Files.writeString(Path.of(output), "checkpoint");
            String result = "CATCHME_AGENT_EVENT {\"event_type\":\"training_result\","
                    + "\"scenario_id\":26,\"episode_count\":1,\"episode_completed\":true,"
                    + "\"investigator_transition_count\":1,\"investigator_training_steps\":1,"
                    + "\"investigator_checkpoint\":" + new ObjectMapper().writeValueAsString(output) + "}\n";
            return process((result + new String(episodeResult(), StandardCharsets.UTF_8))
                    .getBytes(StandardCharsets.UTF_8), true);
        }, 26L);

        var run = service.startInvestigatorTraining(26L, null);
        executor.runNext();

        assertEquals("COMPLETED", service.get(run.runId()).status(), service.get(run.runId()).message());
        assertTrue(command.get().contains("--train-investigator"));
        assertTrue(command.get().contains("--initialize-fresh"));
        assertFalse(command.get().contains("--train-fraudster"));
        assertFalse(command.get().contains("--investigator-checkpoint"));
        String output = command.get().get(command.get().indexOf("--investigator-output-checkpoint") + 1);
        assertTrue(output.contains(run.runId()));
        assertFalse(authorized(token.get(), 27L, run.runId()));
        service.shutdown();
    }

    @Test
    void cancellationWhileQueuedPreventsCredentialIssuanceAndChildLaunch() throws Exception {
        var executor = new QueuedExecutor();
        AtomicReference<Process> started = new AtomicReference<>();
        AgentRunService service = service(executor, builder -> {
            started.set(process(episodeResult(), true));
            return started.get();
        }, 8L);

        var run = service.start(8L);
        service.cancel(run.runId());
        executor.runNext();

        assertNull(started.get());
        assertEquals("FAILED", service.get(run.runId()).status());
        service.shutdown();
    }

    @Test
    void cancellationDuringStartupSerializesWithChildLaunchAndImmediatelyRevokes() throws Exception {
        var executor = new QueuedExecutor();
        CountDownLatch inStart = new CountDownLatch(1);
        CountDownLatch allowStart = new CountDownLatch(1);
        AtomicReference<String> token = new AtomicReference<>();
        AtomicReference<FakeProcess> child = new AtomicReference<>();
        AgentRunService service = service(executor, builder -> {
            token.set(builder.environment().get(FraudsterRunCredentialService.ENVIRONMENT_VARIABLE));
            inStart.countDown();
            await(allowStart);
            FakeProcess process = process(new byte[0], false);
            child.set(process);
            return process;
        }, 9L);

        var run = service.start(9L);
        Thread worker = new Thread(executor::runNext);
        worker.start();
        assertTrue(inStart.await(2, TimeUnit.SECONDS));
        Thread canceller = new Thread(() -> service.cancel(run.runId()));
        canceller.start();
        allowStart.countDown();
        canceller.join(2_000);
        worker.join(2_000);

        assertFalse(canceller.isAlive());
        assertFalse(authorized(token.get(), 9L, run.runId()));
        assertNotNull(child.get());
        assertTrue(child.get().destroyed);
        service.shutdown();
    }

    @Test
    void cancellationAfterChildStartsRevokesBeforeReturning() throws Exception {
        var executor = new QueuedExecutor();
        CountDownLatch childStarted = new CountDownLatch(1);
        AtomicReference<String> token = new AtomicReference<>();
        AtomicReference<FakeProcess> child = new AtomicReference<>();
        AgentRunService service = service(executor, builder -> {
            token.set(builder.environment().get(FraudsterRunCredentialService.ENVIRONMENT_VARIABLE));
            FakeProcess process = process(new byte[0], false);
            child.set(process);
            childStarted.countDown();
            return process;
        }, 10L);

        var run = service.start(10L);
        Thread worker = new Thread(executor::runNext);
        worker.start();
        assertTrue(childStarted.await(2, TimeUnit.SECONDS));
        service.cancel(run.runId());

        assertFalse(authorized(token.get(), 10L, run.runId()));
        assertTrue(child.get().destroyed);
        assertThrows(AgentRunService.AgentRunConflictException.class, () -> service.cancel(run.runId()));
        assertFalse(authorized(token.get(), 10L, run.runId()));
        worker.join(2_000);
        service.shutdown();
    }

    @Test
    void timeoutRevokesCredentialBeforeProcessCleanup() throws Exception {
        var executor = new QueuedExecutor();
        AtomicReference<String> token = new AtomicReference<>();
        AtomicReference<FakeProcess> child = new AtomicReference<>();
        AgentRunService service = serviceTimeout(executor, builder -> {
            token.set(builder.environment().get(FraudsterRunCredentialService.ENVIRONMENT_VARIABLE));
            FakeProcess process = process(new byte[0], false);
            child.set(process);
            return process;
        }, 1, 11L);

        var run = service.start(11L);
        executor.runNext();

        assertFalse(authorized(token.get(), 11L, run.runId()));
        assertEquals("FAILED", service.get(run.runId()).status());
        assertTrue(child.get().destroyed);
        service.shutdown();
    }

    @Test
    void launchFailureAndExecutionExceptionRevokeCredentials() throws Exception {
        var launchQueue = new QueuedExecutor();
        AtomicReference<String> launchToken = new AtomicReference<>();
        AgentRunService launchService = service(launchQueue, builder -> {
            launchToken.set(builder.environment().get(FraudsterRunCredentialService.ENVIRONMENT_VARIABLE));
            throw new IOException("launch failed " + launchToken.get());
        }, 12L);
        var launchRun = launchService.start(12L);
        launchQueue.runNext();
        assertFalse(authorized(launchToken.get(), 12L, launchRun.runId()));
        assertEquals("FAILED", launchService.get(launchRun.runId()).status());
        assertFalse(launchService.get(launchRun.runId()).message().contains(launchToken.get()));
        launchService.shutdown();

        var exceptionQueue = new QueuedExecutor();
        AtomicReference<String> exceptionToken = new AtomicReference<>();
        AgentRunService exceptionService = service(exceptionQueue, builder -> {
            exceptionToken.set(builder.environment().get(FraudsterRunCredentialService.ENVIRONMENT_VARIABLE));
            throw new IllegalStateException("injected start error");
        }, 13L);
        var exceptionRun = exceptionService.start(13L);
        exceptionQueue.runNext();
        assertFalse(authorized(exceptionToken.get(), 13L, exceptionRun.runId()));
        assertEquals("FAILED", exceptionService.get(exceptionRun.runId()).status());
        exceptionService.shutdown();
    }

    @Test
    void exceptionAfterChildLaunchImmediatelyRevokesCredential() throws Exception {
        var executor = new QueuedExecutor();
        AtomicReference<String> token = new AtomicReference<>();
        AtomicReference<FakeProcess> child = new AtomicReference<>();
        AgentRunService service = service(executor, builder -> {
            token.set(builder.environment().get(FraudsterRunCredentialService.ENVIRONMENT_VARIABLE));
            FakeProcess process = new FakeProcess(new byte[0], false, 0, true, false, false);
            child.set(process);
            return process;
        }, 17L);

        var run = service.start(17L);
        executor.runNext();

        assertFalse(authorized(token.get(), 17L, run.runId()));
        assertEquals("FAILED", service.get(run.runId()).status());
        assertTrue(child.get().destroyed);
        service.shutdown();
    }

    @Test
    void unexpectedErrorDuringStartupStillRevokesAndCommitsFailure() throws Exception {
        var executor = new QueuedExecutor();
        AtomicReference<String> token = new AtomicReference<>();
        AgentRunService service = service(executor, builder -> {
            token.set(builder.environment().get(FraudsterRunCredentialService.ENVIRONMENT_VARIABLE));
            throw new AssertionError("injected fatal startup error");
        }, 24L);

        var run = service.start(24L);
        assertThrows(AssertionError.class, executor::runNext);

        assertEquals("FAILED", service.get(run.runId()).status());
        assertFalse(authorized(token.get(), 24L, run.runId()));
        service.shutdown();
    }

    @Test
    void malformedOutputTerminatesChildAndRevokesCredential() throws Exception {
        var executor = new QueuedExecutor();
        AtomicReference<String> token = new AtomicReference<>();
        AtomicReference<FakeProcess> child = new AtomicReference<>();
        CountDownLatch childCreated = new CountDownLatch(1);
        AgentRunService service = service(executor, builder -> {
            token.set(builder.environment().get(FraudsterRunCredentialService.ENVIRONMENT_VARIABLE));
            FakeProcess process = process("CATCHME_AGENT_EVENT not-json\n".getBytes(StandardCharsets.UTF_8), false);
            child.set(process);
            childCreated.countDown();
            return process;
        }, 18L);

        var run = service.start(18L);
        Thread worker = new Thread(executor::runNext);
        worker.start();
        assertTrue(childCreated.await(2, TimeUnit.SECONDS));
        assertTrue(child.get().outputConsumed.await(2, TimeUnit.SECONDS));
        worker.join(2_000);

        assertFalse(worker.isAlive());
        assertEquals("FAILED", service.get(run.runId()).status());
        assertFalse(authorized(token.get(), 18L, run.runId()));
        assertTrue(child.get().destroyed);
        service.shutdown();
    }

    @Test
    void outputReaderIoFailureTerminatesChildAndRevokesCredential() throws Exception {
        var executor = new QueuedExecutor();
        AtomicReference<String> token = new AtomicReference<>();
        AtomicReference<FakeProcess> child = new AtomicReference<>();
        CountDownLatch childCreated = new CountDownLatch(1);
        AgentRunService service = service(executor, builder -> {
            token.set(builder.environment().get(FraudsterRunCredentialService.ENVIRONMENT_VARIABLE));
            FakeProcess process = new FakeProcess(new byte[0], false, 0, false, true, false);
            child.set(process);
            childCreated.countDown();
            return process;
        }, 19L);

        var run = service.start(19L);
        Thread worker = new Thread(executor::runNext);
        worker.start();
        assertTrue(childCreated.await(2, TimeUnit.SECONDS));
        assertTrue(child.get().outputConsumed.await(2, TimeUnit.SECONDS));
        worker.join(2_000);

        assertFalse(worker.isAlive());
        assertEquals("FAILED", service.get(run.runId()).status());
        assertFalse(authorized(token.get(), 19L, run.runId()));
        assertTrue(child.get().destroyed);
        service.shutdown();
    }

    @Test
    void continuePipeFailureTerminatesChildAndRevokesCredential() throws Exception {
        var executor = new QueuedExecutor();
        AtomicReference<String> token = new AtomicReference<>();
        AtomicReference<FakeProcess> child = new AtomicReference<>();
        CountDownLatch childCreated = new CountDownLatch(1);
        byte[] pauseEvent = ("CATCHME_AGENT_EVENT {\"event_type\":\"round_paused\",\"round_number\":1}\n")
                .getBytes(StandardCharsets.UTF_8);
        AgentRunService service = service(executor, builder -> {
            token.set(builder.environment().get(FraudsterRunCredentialService.ENVIRONMENT_VARIABLE));
            FakeProcess process = new FakeProcess(pauseEvent, false, 0, false, false, true);
            child.set(process);
            childCreated.countDown();
            return process;
        }, 20L);

        var run = service.start(20L);
        Thread worker = new Thread(executor::runNext);
        worker.start();
        assertTrue(childCreated.await(2, TimeUnit.SECONDS));
        assertTrue(child.get().outputConsumed.await(2, TimeUnit.SECONDS));
        assertThrows(AgentRunService.AgentRunConflictException.class,
                () -> service.continueRun(run.runId()));
        worker.join(2_000);

        assertFalse(worker.isAlive());
        assertEquals("FAILED", service.get(run.runId()).status());
        assertFalse(authorized(token.get(), 20L, run.runId()));
        assertTrue(child.get().destroyed);
        service.shutdown();
    }

    @Test
    void overallDeadlineIncludesStartupAndMaximumTimeoutIsAccepted() throws Exception {
        AtomicLong ticker = new AtomicLong(100);
        var executor = new QueuedExecutor();
        AtomicReference<FakeProcess> child = new AtomicReference<>();
        AgentRunService shortRun = serviceTimeout(executor, builder -> {
            ticker.addAndGet(TimeUnit.MILLISECONDS.toNanos(4_500));
            FakeProcess process = process(episodeResult(), true);
            child.set(process);
            return process;
        }, 5, ticker::get, 21L);

        var run = shortRun.start(21L);
        executor.runNext();
        assertTrue(child.get().lastWaitNanos > 0);
        assertTrue(child.get().lastWaitNanos < TimeUnit.SECONDS.toNanos(1));
        assertEquals("COMPLETED", shortRun.get(run.runId()).status());
        shortRun.shutdown();

        AtomicLong maxTicker = new AtomicLong(0);
        var maxExecutor = new QueuedExecutor();
        AtomicReference<FakeProcess> maxChild = new AtomicReference<>();
        AgentRunService maxRun = serviceTimeout(maxExecutor, builder -> {
            FakeProcess process = process(episodeResult(), true);
            maxChild.set(process);
            return process;
        }, AgentRunService.MAX_RUN_TIMEOUT_SECONDS, maxTicker::get, 22L);
        var maxRecord = maxRun.start(22L);
        maxExecutor.runNext();
        assertTrue(maxChild.get().lastWaitNanos > 0);
        assertTrue(maxChild.get().lastWaitNanos
                <= TimeUnit.SECONDS.toNanos(AgentRunService.MAX_RUN_TIMEOUT_SECONDS));
        assertEquals("COMPLETED", maxRun.get(maxRecord.runId()).status());
        maxRun.shutdown();
    }

    @Test
    void invalidTimeoutsAreRejectedAndDefaultRemainsThreeHundredSeconds() throws Exception {
        assertEquals(300, AgentRunService.DEFAULT_RUN_TIMEOUT_SECONDS);
        assertTrue(AgentRunService.MAX_RUN_TIMEOUT_SECONDS == TimeUnit.HOURS.toSeconds(24));
        for (long invalid : new long[]{0, -1, AgentRunService.MAX_RUN_TIMEOUT_SECONDS + 1}) {
            var executor = new QueuedExecutor();
            AgentRunService service = serviceTimeout(executor, builder -> process(episodeResult(), true), invalid, 23L);
            assertThrows(IllegalStateException.class, () -> service.start(23L));
            assertTrue(executor.tasks.isEmpty());
            service.shutdown();
        }
    }

    @Test
    void concurrentRunsKeepCredentialsIsolatedAndRevocationIsIdempotent() throws Exception {
        var executor = new QueuedExecutor();
        var credentialsByRun = new ConcurrentHashMap<String, String>();
        var scenarioByRun = new ConcurrentHashMap<String, Long>();
        var childByRun = new ConcurrentHashMap<String, FakeProcess>();
        AtomicReference<String> firstRunId = new AtomicReference<>();
        AtomicReference<String> secondRunId = new AtomicReference<>();
        AtomicBoolean crossUseRejected = new AtomicBoolean();
        CountDownLatch firstChildStarted = new CountDownLatch(1);
        CountDownLatch bothChildrenStarted = new CountDownLatch(2);
        AgentRunService service = service(executor, builder -> {
            String runId = builder.environment().get(FraudsterRunCredentialService.RUN_ID_ENVIRONMENT_VARIABLE);
            String token = builder.environment().get(FraudsterRunCredentialService.ENVIRONMENT_VARIABLE);
            long scenarioId = Long.parseLong(builder.command().get(3));
            credentialsByRun.put(runId, token);
            scenarioByRun.put(runId, scenarioId);
            if (credentialsByRun.size() == 2) {
                String oneRun = firstRunId.get();
                String twoRun = secondRunId.get();
                crossUseRejected.set(
                        !authorized(credentialsByRun.get(oneRun), scenarioByRun.get(twoRun), twoRun)
                                && !authorized(credentialsByRun.get(twoRun), scenarioByRun.get(oneRun), oneRun));
            }
            FakeProcess process = process(new byte[0], false);
            childByRun.put(runId, process);
            if (firstChildStarted.getCount() == 1) firstChildStarted.countDown();
            bothChildrenStarted.countDown();
            return process;
        }, 14L, 15L);

        var first = service.start(14L);
        var second = service.start(15L);
        firstRunId.set(first.runId());
        secondRunId.set(second.runId());
        assertNotEquals(first.runId(), second.runId());
        Thread firstWorker = new Thread(executor::runNext);
        firstWorker.start();
        assertTrue(firstChildStarted.await(2, TimeUnit.SECONDS));
        Thread secondWorker = new Thread(executor::runNext);
        secondWorker.start();
        assertTrue(bothChildrenStarted.await(2, TimeUnit.SECONDS));
        assertTrue(crossUseRejected.get());
        service.cancel(first.runId());
        service.cancel(second.runId());
        firstWorker.join(2_000);
        secondWorker.join(2_000);
        assertTrue(childByRun.get(first.runId()).destroyed);
        assertTrue(childByRun.get(second.runId()).destroyed);
        credentials.revokeRun(first.runId());
        credentials.revokeRun(first.runId());
        assertFalse(authorized(credentialsByRun.get(first.runId()), 14L, first.runId()));
        assertFalse(authorized(credentialsByRun.get(second.runId()), 15L, second.runId()));
        service.shutdown();
    }

    @Test
    void capturedOutputAndErrorPathsNeverExposeCredentialInRunSnapshot() throws Exception {
        var executor = new QueuedExecutor();
        AtomicReference<String> token = new AtomicReference<>();
        AgentRunService service = service(executor, builder -> {
            String value = builder.environment().get(FraudsterRunCredentialService.ENVIRONMENT_VARIABLE);
            token.set(value);
            String error = "CATCHME_AGENT_EVENT {\"event_type\":\"runner_error\",\"message\":\"" + value + "\"}\n";
            return new FakeProcess(error.getBytes(StandardCharsets.UTF_8), true, 1);
        }, 16L);

        var run = service.start(16L);
        executor.runNext();
        var result = service.get(run.runId());
        assertFalse(result.message().contains(token.get()));
        assertTrue(result.message().contains("[credential redacted]"));
        assertTrue(result.events().stream().noneMatch(event -> event.toString().contains(token.get())));
        service.shutdown();
    }

    private AgentRunService service(QueuedExecutor executor, AgentRunService.ProcessStarter starter,
                                    Long... scenarioIds) throws IOException {
        return serviceTimeout(executor, starter, 60, scenarioIds);
    }

    private AgentRunService serviceTimeout(QueuedExecutor executor, AgentRunService.ProcessStarter starter,
                                          long timeoutSeconds, Long... scenarioIds) throws IOException {
        return serviceTimeout(executor, starter, timeoutSeconds, System::nanoTime, scenarioIds);
    }

    private AgentRunService serviceTimeout(QueuedExecutor executor, AgentRunService.ProcessStarter starter,
                                          long timeoutSeconds, LongSupplier ticker, Long... scenarioIds) throws IOException {
        FraudScenarioService scenarios = mock(FraudScenarioService.class);
        for (Long id : scenarioIds) {
            FraudScenarioResponse response = mock(FraudScenarioResponse.class);
            when(response.getStatus()).thenReturn("ACTIVE");
            when(scenarios.findScenario(id)).thenReturn(Optional.of(response));
        }
        Path directory = Files.createTempDirectory("agent-run-test");
        Path runner = Files.createFile(directory.resolve("runner.py"));
        Path fraudster = Files.createFile(directory.resolve("fraudster.json"));
        Path investigator = Files.createFile(directory.resolve("investigator.json"));
        return new AgentRunService(scenarios, credentials, new ObjectMapper(), "python",
                runner.toString(), fraudster.toString(), investigator.toString(), 60, timeoutSeconds,
                executor, starter, ticker);
    }

    private boolean authorized(String token, long scenario, String run) {
        return credentials.authorizes(token, scenario, run, ROLE, OPERATION);
    }

    private static byte[] episodeResult() {
        return ("CATCHME_AGENT_EVENT {\"event_type\":\"episode_result\",\"final_state\":{\"status\":\"COMPLETED\"}}\n")
                .getBytes(StandardCharsets.UTF_8);
    }

    private static FakeProcess process(byte[] output, boolean exits) {
        return new FakeProcess(output, exits);
    }

    private static void await(CountDownLatch latch) {
        try {
            if (!latch.await(2, TimeUnit.SECONDS)) throw new AssertionError("test synchronization timed out");
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new AssertionError(e);
        }
    }

    private static final class QueuedExecutor extends AbstractExecutorService {
        private final Queue<Runnable> tasks = new ArrayDeque<>();
        private boolean shutdown;

        @Override public synchronized void execute(Runnable command) { tasks.add(command); }
        void runNext() {
            Runnable task;
            synchronized (this) { task = tasks.poll(); }
            if (task != null) task.run();
        }
        @Override public synchronized void shutdown() { shutdown = true; }
        @Override public synchronized java.util.List<Runnable> shutdownNow() { shutdown = true; return new java.util.ArrayList<>(tasks); }
        @Override public synchronized boolean isShutdown() { return shutdown; }
        @Override public synchronized boolean isTerminated() { return shutdown && tasks.isEmpty(); }
        @Override public boolean awaitTermination(long timeout, TimeUnit unit) { return isTerminated(); }
    }

    private static final class FakeProcess extends Process {
        private final ByteArrayInputStream input;
        private final ByteArrayOutputStream output = new ByteArrayOutputStream();
        private final boolean exits;
        private final int exitCode;
        private final boolean failReadingRuntime;
        private final boolean failReadingIo;
        private final boolean failPipeWrite;
        private final CountDownLatch destroyedLatch = new CountDownLatch(1);
        final CountDownLatch outputConsumed = new CountDownLatch(1);
        volatile long lastWaitNanos;
        volatile boolean destroyed;
        FakeProcess(byte[] input, boolean exits) { this(input, exits, 0, false, false, false); }
        FakeProcess(byte[] input, boolean exits, int exitCode) { this(input, exits, exitCode, false, false, false); }
        FakeProcess(byte[] input, boolean exits, int exitCode, boolean failReadingRuntime) {
            this(input, exits, exitCode, failReadingRuntime, false, false);
        }
        FakeProcess(byte[] input, boolean exits, int exitCode, boolean failReadingRuntime,
                    boolean failReadingIo, boolean failPipeWrite) {
            this.input = new ByteArrayInputStream(input); this.exits = exits; this.exitCode = exitCode;
            this.failReadingRuntime = failReadingRuntime;
            this.failReadingIo = failReadingIo;
            this.failPipeWrite = failPipeWrite;
        }
        @Override public OutputStream getOutputStream() {
            if (!failPipeWrite) return output;
            return new OutputStream() {
                @Override public void write(int value) throws IOException { throw new IOException("injected pipe failure"); }
            };
        }
        @Override public InputStream getInputStream() {
            if (failReadingRuntime) {
                outputConsumed.countDown();
                throw new IllegalStateException("injected output reader failure");
            }
            if (failReadingIo) {
                return new InputStream() {
                    @Override public int read() throws IOException {
                        outputConsumed.countDown();
                        throw new IOException("injected output reader I/O failure");
                    }
                };
            }
            return new InputStream() {
                private boolean signalEof(int result) {
                    if (result < 0) outputConsumed.countDown();
                    return result < 0;
                }
                @Override public int read() { int value = input.read(); signalEof(value); return value; }
                @Override public int read(byte[] bytes, int offset, int length) {
                    int count = input.read(bytes, offset, length); signalEof(count); return count;
                }
                @Override public void close() throws IOException { input.close(); }
            };
        }
        @Override public java.io.InputStream getErrorStream() { return new ByteArrayInputStream(new byte[0]); }
        @Override public int waitFor() { return 0; }
        @Override public boolean waitFor(long timeout, TimeUnit unit) throws InterruptedException {
            lastWaitNanos = unit.toNanos(timeout);
            return exits || destroyedLatch.await(timeout, unit);
        }
        @Override public int exitValue() { return exitCode; }
        @Override public void destroy() { destroyed = true; destroyedLatch.countDown(); }
        @Override public Process destroyForcibly() { destroy(); return this; }
        @Override public boolean isAlive() { return !exits && !destroyed; }
    }
}
