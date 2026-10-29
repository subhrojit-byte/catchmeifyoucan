package catchmeifyoucan.service;

import catchmeifyoucan.dto.AgentRunResponse;
import catchmeifyoucan.dto.FraudScenarioResponse;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.LongSupplier;
import java.util.regex.Pattern;

@Service
public class AgentRunService {
    private static final Logger LOGGER = LoggerFactory.getLogger(AgentRunService.class);
    private static final String EVENT_PREFIX = "CATCHME_AGENT_EVENT ";
    private static final int MAX_EVENTS = 256;
    private static final Pattern DATABASE_URL = Pattern.compile(
            "(?i)(?:postgres(?:ql)?|mysql)://\\S+"
    );
    private static final Pattern URL_CREDENTIALS = Pattern.compile(
            "(://)[^/@\\s]+@"
    );

    private final FraudScenarioService scenarioService;
    private final FraudsterRunCredentialService fraudsterCredentialService;
    private final ObjectMapper objectMapper;
    private final String pythonExecutable;
    private final String configuredRunnerPath;
    private final String configuredFraudsterCheckpoint;
    private final String configuredInvestigatorCheckpoint;
    private final int maxActions;
    private final long timeoutSeconds;
    static final long DEFAULT_RUN_TIMEOUT_SECONDS = 300;
    static final long MAX_RUN_TIMEOUT_SECONDS = 24 * 60 * 60;
    private final ExecutorService workers;
    private final ProcessStarter processStarter;
    private final LongSupplier nanoClock;
    private final ExecutorService outputReaders = java.util.concurrent.Executors.newFixedThreadPool(2);
    private final Map<String, RunRecord> runs = new ConcurrentHashMap<>();
    private final Map<Long, String> activeScenarioRuns = new ConcurrentHashMap<>();
    private final Object startLock = new Object();
    private final AtomicBoolean stopping = new AtomicBoolean();

    @Autowired
    public AgentRunService(
            FraudScenarioService scenarioService,
            FraudsterRunCredentialService fraudsterCredentialService,
            ObjectMapper objectMapper,
            @Value("${agents.python-executable:python}") String pythonExecutable,
            @Value("${agents.runner-path:}") String configuredRunnerPath,
            @Value("${agents.fraudster-checkpoint:}") String configuredFraudsterCheckpoint,
            @Value("${agents.investigator-checkpoint:}") String configuredInvestigatorCheckpoint,
            @Value("${agents.max-actions:60}") int maxActions,
            @Value("${agents.timeout-seconds:" + DEFAULT_RUN_TIMEOUT_SECONDS + "}") long timeoutSeconds) {
        this(scenarioService, fraudsterCredentialService, objectMapper, pythonExecutable,
                configuredRunnerPath, configuredFraudsterCheckpoint, configuredInvestigatorCheckpoint,
                maxActions, timeoutSeconds,
                new ThreadPoolExecutor(2, 2, 0L, TimeUnit.MILLISECONDS,
                        new ArrayBlockingQueue<>(8), new ThreadPoolExecutor.AbortPolicy()),
                ProcessBuilder::start, System::nanoTime);
    }

    AgentRunService(
            FraudScenarioService scenarioService,
            FraudsterRunCredentialService fraudsterCredentialService,
            ObjectMapper objectMapper,
            String pythonExecutable,
            String configuredRunnerPath,
            String configuredFraudsterCheckpoint,
            String configuredInvestigatorCheckpoint,
            int maxActions,
            long timeoutSeconds,
            ExecutorService workers,
            ProcessStarter processStarter) {
        this(scenarioService, fraudsterCredentialService, objectMapper, pythonExecutable,
                configuredRunnerPath, configuredFraudsterCheckpoint, configuredInvestigatorCheckpoint,
                maxActions, timeoutSeconds, workers, processStarter, System::nanoTime);
    }

    AgentRunService(
            FraudScenarioService scenarioService,
            FraudsterRunCredentialService fraudsterCredentialService,
            ObjectMapper objectMapper,
            String pythonExecutable,
            String configuredRunnerPath,
            String configuredFraudsterCheckpoint,
            String configuredInvestigatorCheckpoint,
            int maxActions,
            long timeoutSeconds,
            ExecutorService workers,
            ProcessStarter processStarter,
            LongSupplier nanoClock) {
        this.scenarioService = scenarioService;
        this.fraudsterCredentialService = fraudsterCredentialService;
        this.objectMapper = objectMapper;
        this.pythonExecutable = pythonExecutable;
        this.configuredRunnerPath = configuredRunnerPath;
        this.configuredFraudsterCheckpoint = configuredFraudsterCheckpoint;
        this.configuredInvestigatorCheckpoint = configuredInvestigatorCheckpoint;
        this.maxActions = maxActions;
        this.timeoutSeconds = timeoutSeconds;
        this.workers = workers;
        this.processStarter = processStarter;
        this.nanoClock = nanoClock;
    }

    public AgentRunResponse start(Long scenarioId) {
        return start(scenarioId, false);
    }

    public AgentRunResponse startFraudsterTraining(Long scenarioId) {
        return start(scenarioId, true, false, null);
    }

    private AgentRunResponse start(Long scenarioId, boolean trainFraudster) {
        return start(scenarioId, trainFraudster, false, null);
    }

    public AgentRunResponse startInvestigatorTraining(Long scenarioId, String priorCheckpoint) {
        return start(scenarioId, false, true, priorCheckpoint);
    }

    public AgentRunResponse startHumanFraudsterMatch(Long scenarioId) {
        return start(scenarioId, false, false, null, true);
    }

    public AgentRunResponse startHeuristicSearch(Long scenarioId) {
        return start(scenarioId, false, false, null, false, true);
    }

    private AgentRunResponse start(Long scenarioId, boolean trainFraudster,
                                   boolean trainInvestigator, String priorCheckpoint) {
        return start(scenarioId, trainFraudster, trainInvestigator, priorCheckpoint, false);
    }

    private AgentRunResponse start(Long scenarioId, boolean trainFraudster,
                                   boolean trainInvestigator, String priorCheckpoint,
                                   boolean humanFraudster) {
        return start(scenarioId, trainFraudster, trainInvestigator, priorCheckpoint,
                humanFraudster, false);
    }

    private AgentRunResponse start(Long scenarioId, boolean trainFraudster,
                                   boolean trainInvestigator, String priorCheckpoint,
                                   boolean humanFraudster, boolean heuristicSearch) {
        if (scenarioId == null || scenarioId <= 0) {
            throw new IllegalArgumentException("A positive scenario ID is required.");
        }
        FraudScenarioResponse scenario = scenarioService.findScenario(scenarioId)
                .orElseThrow(() -> new AgentRunNotFoundException("Scenario not found."));
        if (!"ACTIVE".equals(scenario.getStatus())) {
            throw new AgentRunConflictException("Learned agents can only start on an ACTIVE scenario.");
        }
        String runId = UUID.randomUUID().toString();
        RunnerConfiguration configuration = resolveConfiguration(
                trainFraudster, trainInvestigator, priorCheckpoint, runId, humanFraudster, heuristicSearch);
        RunRecord run = new RunRecord(
                runId, scenarioId, fraudsterCredentialService, trainFraudster || trainInvestigator,
                trainInvestigator, humanFraudster,
                heuristicSearch, configuration.fraudsterOutput(), configuration.investigatorOutput());
        synchronized (startLock) {
            if (activeScenarioRuns.containsKey(scenarioId)) {
                throw new AgentRunConflictException(
                        "A learned-agent run is already active for this scenario."
                );
            }
            activeScenarioRuns.put(scenarioId, run.runId);
            runs.put(run.runId, run);
            try {
                workers.execute(() -> execute(run, configuration));
            } catch (RuntimeException error) {
                activeScenarioRuns.remove(scenarioId, run.runId);
                runs.remove(run.runId);
                throw new AgentRunConflictException(
                        "The learned-agent runner is busy. Try again shortly."
                );
            }
        }
        return run.snapshot();
    }

    public AgentRunResponse get(String runId) {
        RunRecord run = runs.get(runId);
        if (run == null) {
            throw new AgentRunNotFoundException("Learned-agent run not found.");
        }
        return run.snapshot();
    }

    public AgentRunResponse continueRun(String runId) {
        RunRecord run = requireRun(runId);
        run.continueRound();
        return run.snapshot();
    }

    public AgentRunResponse cancel(String runId) {
        RunRecord run = requireRun(runId);
        run.cancel();
        return run.snapshot();
    }

    private RunRecord requireRun(String runId) {
        RunRecord run = runs.get(runId);
        if (run == null) {
            throw new AgentRunNotFoundException("Learned-agent run not found.");
        }
        return run;
    }

    private RunnerConfiguration resolveConfiguration(boolean trainFraudster, boolean trainInvestigator,
                                                     String priorCheckpoint, String runId,
                                                     boolean humanFraudster, boolean heuristicSearch) {
        Path runner = heuristicSearch ? resolveHeuristicRunnerPath() : resolveRunnerPath(configuredRunnerPath);
        if (trainInvestigator && priorCheckpoint != null && priorCheckpoint.isBlank()) {
            throw new IllegalArgumentException("investigatorCheckpoint must be a non-empty path when supplied.");
        }
        Path fraudster = null;
        Path investigator = null;
        if (heuristicSearch) {
            // This dedicated runner never resolves or loads RL checkpoints.
        } else if (humanFraudster) {
            investigator = resolveCheckpoint(
                    configuredInvestigatorCheckpoint,
                    runner.getParent().resolve("investigator-trained-fresh-20261025.json"),
                    runner.getParent(), "investigator");
        } else if (!trainFraudster && !trainInvestigator) {
            fraudster = resolveCheckpoint(
                    configuredFraudsterCheckpoint,
                    runner.getParent().resolve("fraudster-trained-run-120d17a1-5012-45c9-89a8-97b4dab1a5fb.json"),
                    runner.getParent(),
                    "fraudster"
            );
            investigator = resolveCheckpoint(
                    configuredInvestigatorCheckpoint,
                    runner.getParent().resolve("investigator-trained-fresh-20261025.json"),
                    runner.getParent(),
                    "investigator"
            );
        }
        if (pythonExecutable == null || pythonExecutable.isBlank()) {
            throw new IllegalStateException("Configure agents.python-executable with a Python interpreter path.");
        }
        if (maxActions <= 0 || timeoutSeconds <= 0 || timeoutSeconds > MAX_RUN_TIMEOUT_SECONDS) {
            throw new IllegalStateException("agents.max-actions must be positive and agents.timeout-seconds must be between 1 and "
                    + MAX_RUN_TIMEOUT_SECONDS + ".");
        }
        Path fraudsterOutput = null;
        Path investigatorOutput = null;
        if (trainInvestigator) {
            if (priorCheckpoint != null) {
                investigator = resolveCheckpoint(priorCheckpoint, null, runner.getParent(), "investigator");
            }
            investigatorOutput = runner.getParent().resolve("investigator-managed-run-" + runId + ".json");
            if (Files.exists(investigatorOutput)) {
                throw new IllegalStateException("Run-specific training checkpoint path already exists.");
            }
        }
        if (trainFraudster) {
            fraudsterOutput = runner.getParent().resolve("fraudster-trained-run-" + runId + ".json");
            investigatorOutput = runner.getParent().resolve("investigator-trained-run-" + runId + ".json");
            if (Files.exists(fraudsterOutput) || Files.exists(investigatorOutput)) {
                throw new IllegalStateException("Run-specific training checkpoint path already exists.");
            }
        }
        return new RunnerConfiguration(runner, fraudster, investigator, fraudsterOutput, investigatorOutput);
    }

    private Path resolveHeuristicRunnerPath() {
        Path learnedRunner = resolveRunnerPath(configuredRunnerPath);
        Path candidate = learnedRunner.getParent().resolve("run_heuristic_episode.py").normalize();
        if (Files.isRegularFile(candidate)) {
            return candidate.toAbsolutePath().normalize();
        }
        throw new IllegalStateException("Heuristic Search runner was not found beside agents.runner-path.");
    }

    private Path resolveRunnerPath(String configured) {
        if (configured != null && !configured.isBlank()) {
            Path candidate = Paths.get(configured);
            if (!candidate.isAbsolute()) {
                candidate = findRelative(candidate);
            }
            if (candidate != null && Files.isRegularFile(candidate)) {
                return candidate.toAbsolutePath().normalize();
            }
            throw new IllegalStateException(
                    "Python learned-agent runner was not found. Configure agents.runner-path; checked "
                            + configured + "."
            );
        }
        Path relative = Paths.get("rl-agents", "run_learned_episode.py");
        Path candidate = findRelative(relative);
        if (candidate != null && Files.isRegularFile(candidate)) {
            return candidate.toAbsolutePath().normalize();
        }
        throw new IllegalStateException(
                "Python learned-agent runner was not found. Set agents.runner-path to rl-agents/run_learned_episode.py."
        );
    }

    private Path resolveCheckpoint(String configured, Path defaultPath, Path runnerDirectory, String role) {
        if (configured == null || configured.isBlank()) {
            if (Files.isRegularFile(defaultPath)) {
                return defaultPath.toAbsolutePath().normalize();
            }
            throw new IllegalStateException(
                    "Default " + role + " checkpoint was not found at " + defaultPath
                            + ". Configure agents." + role + "-checkpoint."
            );
        }
        Path candidate = Paths.get(configured);
        if (candidate.isAbsolute()) {
            candidate = candidate.normalize();
        } else {
            Path besideRunner = runnerDirectory.resolve(candidate).normalize();
            candidate = Files.isRegularFile(besideRunner) ? besideRunner : findRelative(candidate);
        }
        if (candidate != null && Files.isRegularFile(candidate)) {
            return candidate.toAbsolutePath().normalize();
        }
        throw new IllegalStateException(
                "Configured " + role + " checkpoint was not found: " + configured
                        + ". Set agents." + role + "-checkpoint to a compatible checkpoint file."
        );
    }

    private Path findRelative(Path relative) {
        Path current = Paths.get("").toAbsolutePath().normalize();
        while (current != null) {
            Path candidate = current.resolve(relative).normalize();
            if (Files.exists(candidate)) {
                return candidate;
            }
            current = current.getParent();
        }
        return null;
    }

    private void execute(RunRecord run, RunnerConfiguration configuration) {
        Process process = null;
        Future<?> outputReader = null;
        String fraudsterCredential = null;
        try {
            List<String> command = new ArrayList<>(List.of(
                    pythonExecutable,
                    configuration.runner().toString(),
                    "--scenario-id", run.scenarioId.toString(),
                    "--max-actions", Integer.toString(maxActions)
            ));
            if (run.heuristicSearch) {
                // Use only the common scenario and action-limit arguments.
            } else if (run.trainFraudster && !run.trainInvestigator) {
                command.add("--train-fraudster");
                command.add("--initialize-fresh");
                command.add("--fraudster-output-checkpoint");
                command.add(configuration.fraudsterOutput().toString());
                command.add("--investigator-output-checkpoint");
                command.add(configuration.investigatorOutput().toString());
            } else if (run.trainInvestigator) {
                command.add("--train-investigator");
                command.add("--investigator-output-checkpoint");
                command.add(configuration.investigatorOutput().toString());
                if (configuration.investigator() == null) command.add("--initialize-fresh");
                else {
                    command.add("--investigator-checkpoint");
                    command.add(configuration.investigator().toString());
                }
            } else if (run.humanFraudster) {
                command.add("--human-fraudster");
                command.add("--investigator-checkpoint");
                command.add(configuration.investigator().toString());
            } else {
                command.add("--fraudster-checkpoint");
                command.add(configuration.fraudster().toString());
                command.add("--investigator-checkpoint");
                command.add(configuration.investigator().toString());
                command.add("--pause-between-rounds");
            }
            ProcessBuilder builder = new ProcessBuilder(command)
                    .directory(configuration.runner().getParent().toFile())
                    .redirectErrorStream(true);
            StartedProcess launched = run.launch(builder, fraudsterCredentialService,
                    processStarter, timeoutSeconds, nanoClock,
                    !run.humanFraudster && !run.heuristicSearch);
            if (launched == null) {
                return;
            }
            process = launched.process();
            fraudsterCredential = launched.credential();
            Process started = process;
            String outputCredential = fraudsterCredential;
            outputReader = outputReaders.submit(() -> consumeOutput(run, started, outputCredential));
            long remainingNanos = launched.deadlineNanos() - nanoClock.getAsLong();
            boolean exited = remainingNanos > 0 && process.waitFor(remainingNanos, TimeUnit.NANOSECONDS);
            if (!exited) {
                run.fail("Learned-agent run timed out. Check runner/API connectivity and agents.timeout-seconds.");
                if (!process.waitFor(2, TimeUnit.SECONDS)) {
                    process.destroyForcibly();
                    process.waitFor(2, TimeUnit.SECONDS);
                }
                return;
            }
            try {
                outputReader.get(5, TimeUnit.SECONDS);
            } catch (TimeoutException error) {
                outputReader.cancel(true);
                run.fail("Could not finish reading learned-agent progress output.");
                return;
            }
            if (process.exitValue() != 0) {
                String message = run.message;
                run.fail(message == null || message.isBlank()
                        ? "Python learned-agent runner failed with exit code " + process.exitValue() + "."
                        : message);
            } else if (!run.hasValidTerminalResult()) {
                run.fail("Python runner exited without a valid terminal episode result.");
            } else if (run.trainFraudster && !run.trainInvestigator
                    && (!Files.isRegularFile(configuration.fraudsterOutput())
                    || !Files.isRegularFile(configuration.investigatorOutput()))) {
                run.fail("Training runner did not save both run-specific checkpoints.");
            } else if (run.trainInvestigator && !Files.isRegularFile(configuration.investigatorOutput())) {
                run.fail("Training runner did not save the run-specific investigator checkpoint.");
            } else {
                run.complete();
            }
        } catch (IOException error) {
            run.fail("Could not start Python learned-agent runner: "
                    + redactCredential(error.getMessage(), fraudsterCredential));
        } catch (InterruptedException error) {
            run.fail("Learned-agent run was interrupted during application shutdown.");
            if (process != null) {
                process.destroyForcibly();
            }
            Thread.currentThread().interrupt();
        } catch (ExecutionException error) {
            run.fail("Could not read Python learned-agent output.");
        } catch (RuntimeException error) {
            run.fail("Learned-agent run failed: " + redactCredential(error.getMessage(), fraudsterCredential));
        } catch (Error error) {
            run.fail("Learned-agent run failed unexpectedly.");
            throw error;
        } finally {
            if (outputReader != null && !outputReader.isDone()) {
                outputReader.cancel(true);
            }
            fraudsterCredentialService.revoke(fraudsterCredential);
            fraudsterCredentialService.revokeRun(run.runId);
            if (process != null && process.isAlive()) {
                process.destroyForcibly();
            }
            run.process = null;
            activeScenarioRuns.remove(run.scenarioId, run.runId);
        }
    }

    private void consumeOutput(RunRecord run, Process process, String credential) {
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (credential != null && !credential.isEmpty()) {
                    line = line.replace(credential, "[credential redacted]");
                }
                if (!line.startsWith(EVENT_PREFIX)) {
                    continue;
                }
                try {
                    JsonNode event = objectMapper.readTree(line.substring(EVENT_PREFIX.length()));
                    if ("runner_diagnostic".equals(event.path("event_type").asText())) {
                        logRunnerDiagnostic(event.path("diagnostic"));
                        continue;
                    }
                    run.accept(event);
                } catch (Exception error) {
                    run.fail("Python runner emitted malformed progress data.");
                }
            }
        } catch (IOException | RuntimeException error) {
            run.fail("Could not read Python learned-agent output.");
        }
    }

    private static void logRunnerDiagnostic(JsonNode diagnostic) {
        String stage = safeDiagnosticValue(diagnostic.path("stage").asText(),
                "connection_open", "read_only_transaction_setup", "terminal_status_query",
                "discovered_candidate_query", "fetch");
        String exceptionType = diagnostic.path("exception_type").asText();
        if (!exceptionType.matches("[A-Za-z_][A-Za-z0-9_]{0,63}")) {
            exceptionType = "UnknownError";
        }
        String sqlstate = diagnostic.path("sqlstate").asText();
        if (!sqlstate.matches("[0-9A-Z]{5}") && !"unavailable".equals(sqlstate)) {
            sqlstate = "unavailable";
        }
        LOGGER.warn("Managed evaluator lookup failed: stage={} exception_type={} sqlstate={}",
                stage, exceptionType, sqlstate);
    }

    private static String safeDiagnosticValue(String value, String... allowed) {
        for (String candidate : allowed) {
            if (candidate.equals(value)) return candidate;
        }
        return "unknown";
    }

    private static String sanitize(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String safe = value.replaceAll("[\\p{Cntrl}&&[^\\t]]", " ").trim();
        safe = DATABASE_URL.matcher(safe).replaceAll("[database URL redacted]");
        safe = URL_CREDENTIALS.matcher(safe).replaceAll("$1[credentials redacted]@");
        return safe.length() > 500 ? safe.substring(0, 500) : safe;
    }

    private static String redactCredential(String value, String credential) {
        if (value == null || credential == null || credential.isEmpty()) return value;
        return value.replace(credential, "[credential redacted]");
    }

    @PreDestroy
    public void shutdown() {
        if (!stopping.compareAndSet(false, true)) {
            return;
        }
        for (RunRecord run : runs.values()) {
            run.fail("Learned-agent run stopped because the application is shutting down.");
            Process process = run.process;
            if (process != null && process.isAlive()) process.destroyForcibly();
        }
        workers.shutdownNow();
        outputReaders.shutdownNow();
    }

    private record RunnerConfiguration(
            Path runner, Path fraudster, Path investigator,
            Path fraudsterOutput, Path investigatorOutput) {
    }

    @FunctionalInterface
    interface ProcessStarter {
        Process start(ProcessBuilder builder) throws IOException;
    }

    private record StartedProcess(Process process, String credential, long deadlineNanos) { }

    static final class RunRecord {
        final String runId;
        final Long scenarioId;
        private final List<JsonNode> events = new ArrayList<>();
        private final FraudsterRunCredentialService credentialService;
        final boolean trainFraudster;
        final boolean trainInvestigator;
        final boolean humanFraudster;
        final boolean heuristicSearch;
        private final String expectedFraudsterCheckpoint;
        private final String expectedInvestigatorCheckpoint;
        private boolean trainingResultAccepted;
        private final AtomicBoolean terminationRequested = new AtomicBoolean();
        volatile String status = "RUNNING";
        volatile String currentAgent;
        volatile Integer pausedAfterRound;
        volatile JsonNode latestAction;
        volatile JsonNode scenarioState;
        volatile JsonNode latestEvidence;
        volatile JsonNode finalState;
        volatile Integer actionsAttempted;
        volatile String message;
        volatile Process process;

        RunRecord(String runId, Long scenarioId) {
            this(runId, scenarioId, null, false);
        }

        RunRecord(String runId, Long scenarioId, FraudsterRunCredentialService credentialService) {
            this(runId, scenarioId, credentialService, false);
        }

        RunRecord(String runId, Long scenarioId, FraudsterRunCredentialService credentialService,
                  boolean trainFraudster) {
            this(runId, scenarioId, credentialService, trainFraudster, null, null);
        }

        RunRecord(String runId, Long scenarioId, FraudsterRunCredentialService credentialService,
                  boolean trainFraudster, Path fraudsterOutput, Path investigatorOutput) {
            this(runId, scenarioId, credentialService, trainFraudster, false, fraudsterOutput, investigatorOutput);
        }

        RunRecord(String runId, Long scenarioId, FraudsterRunCredentialService credentialService,
                  boolean trainFraudster, boolean trainInvestigator, Path fraudsterOutput, Path investigatorOutput) {
            this(runId, scenarioId, credentialService, trainFraudster, trainInvestigator,
                    false, fraudsterOutput, investigatorOutput);
        }

        RunRecord(String runId, Long scenarioId, FraudsterRunCredentialService credentialService,
                  boolean trainFraudster, boolean trainInvestigator, boolean humanFraudster,
                  Path fraudsterOutput, Path investigatorOutput) {
            this(runId, scenarioId, credentialService, trainFraudster, trainInvestigator,
                    humanFraudster, false, fraudsterOutput, investigatorOutput);
        }

        RunRecord(String runId, Long scenarioId, FraudsterRunCredentialService credentialService,
                  boolean trainFraudster, boolean trainInvestigator, boolean humanFraudster,
                  boolean heuristicSearch, Path fraudsterOutput, Path investigatorOutput) {
            this.runId = runId;
            this.scenarioId = scenarioId;
            this.credentialService = credentialService;
            this.trainFraudster = trainFraudster;
            this.trainInvestigator = trainInvestigator;
            this.humanFraudster = humanFraudster;
            this.heuristicSearch = heuristicSearch;
            this.expectedFraudsterCheckpoint = fraudsterOutput == null ? null : fraudsterOutput.toString();
            this.expectedInvestigatorCheckpoint = investigatorOutput == null ? null : investigatorOutput.toString();
        }

        synchronized StartedProcess launch(ProcessBuilder builder,
                                           FraudsterRunCredentialService credentials,
                                           ProcessStarter starter,
                                           long timeoutSeconds,
                                           LongSupplier nanoClock) throws IOException {
            return launch(builder, credentials, starter, timeoutSeconds, nanoClock, true);
        }

        synchronized StartedProcess launch(ProcessBuilder builder,
                                           FraudsterRunCredentialService credentials,
                                           ProcessStarter starter,
                                           long timeoutSeconds,
                                           LongSupplier nanoClock,
                                           boolean issueFraudsterCredential) throws IOException {
            if (!"RUNNING".equals(status)) return null;
            // timeout-seconds is an overall deadline covering startup, execution, and pauses.
            if (!issueFraudsterCredential) {
                try {
                    builder.environment().remove(FraudsterRunCredentialService.ENVIRONMENT_VARIABLE);
                    builder.environment().remove(FraudsterRunCredentialService.RUN_ID_ENVIRONMENT_VARIABLE);
                    Process child = starter.start(builder);
                    process = child;
                    return new StartedProcess(child, null, nanoClock.getAsLong()
                            + TimeUnit.SECONDS.toNanos(timeoutSeconds));
                } catch (IOException | RuntimeException error) {
                    throw new IOException("Python learned-agent process launch failed.");
                }
            }
            FraudsterRunCredentialService.IssuedCredential issued = credentials.issueForRun(
                    scenarioId, runId, java.time.Duration.ofSeconds(timeoutSeconds));
            String token = issued.token();
            try {
                // Map the credential's exact expiry to a monotonic deadline before starting the child.
                long deadlineBaseNanos = nanoClock.getAsLong();
                long remainingCredentialNanos = credentials.remainingNanos(issued);
                if (remainingCredentialNanos <= 0) {
                    throw new IOException("Credential expired before process startup.");
                }
                long deadlineNanos = deadlineBaseNanos + remainingCredentialNanos;
                FraudsterRunCredentialService.attachToChildEnvironment(builder, token, runId);
                Process child = starter.start(builder);
                process = child;
                return new StartedProcess(child, token, deadlineNanos);
            } catch (IOException | RuntimeException error) {
                credentials.revoke(token);
                throw new IOException("Python learned-agent process launch failed.");
            } finally {
                builder.environment().remove(FraudsterRunCredentialService.ENVIRONMENT_VARIABLE);
            }
        }

        synchronized void accept(JsonNode event) {
            if ("runner_diagnostic".equals(event.path("event_type").asText())) {
                return;
            }
            if ("COMPLETED".equals(status) || "FAILED".equals(status)) {
                return;
            }
            String type = event.path("event_type").asText();
            if ("action".equals(type) || "action_started".equals(type)) {
                currentAgent = sanitize(event.path("agent").asText(null));
                latestAction = event.path("action").deepCopy();
                scenarioState = event.path("state").deepCopy();
                if ("action".equals(type) && event.hasNonNull("evidence")) {
                    latestEvidence = event.path("evidence").deepCopy();
                }
            } else if ("round_paused".equals(type)) {
                status = "PAUSED";
                currentAgent = null;
                pausedAfterRound = event.path("round_number").isInt()
                        ? event.path("round_number").asInt() : null;
                scenarioState = event.path("state").deepCopy();
            } else if ("round_resumed".equals(type)) {
                if ("PAUSED".equals(status)) {
                    status = "RUNNING";
                }
                pausedAfterRound = null;
            } else if ("episode_result".equals(type)) {
                finalState = event.path("final_state").deepCopy();
                scenarioState = finalState;
                actionsAttempted = event.path("actions_attempted").isInt()
                        ? event.path("actions_attempted").asInt() : null;
                if (event.hasNonNull("investigator_evidence")) {
                    latestEvidence = event.path("investigator_evidence").deepCopy();
                }
            } else if ("training_result".equals(type)) {
                trainingResultAccepted = (trainFraudster || trainInvestigator)
                        && event.path("scenario_id").asLong(-1) == scenarioId
                        && event.path("episode_count").asInt(0) == 1
                        && event.path("episode_completed").asBoolean(false)
                        && (trainInvestigator
                            ? event.path("investigator_transition_count").asInt(0) > 0
                                && event.path("investigator_training_steps").asInt(0) > 0
                                && expectedInvestigatorCheckpoint.equals(event.path("investigator_checkpoint").asText(null))
                            : event.path("fraudster_transition_count").asInt(0) > 0
                                && event.path("fraudster_training_steps").asInt(0) > 0
                                && expectedFraudsterCheckpoint.equals(event.path("fraudster_checkpoint").asText(null))
                                && expectedInvestigatorCheckpoint.equals(event.path("investigator_checkpoint").asText(null)));
                if (!trainingResultAccepted) {
                    message = "Training result was incomplete or did not match run-specific checkpoints.";
                }
            } else if ("runner_error".equals(type)) {
                message = sanitize(event.path("message").asText("Python runner failed."));
            }
            if (events.size() == MAX_EVENTS) {
                events.remove(0);
            }
            events.add(event.deepCopy());
        }

        synchronized boolean hasValidTerminalResult() {
            return message == null && (!(trainFraudster || trainInvestigator) || trainingResultAccepted) && finalState != null
                    && ("COMPLETED".equals(finalState.path("status").asText())
                    || "MAX_TURNS_REACHED".equals(finalState.path("status").asText()));
        }

        synchronized void complete() {
            if (!"RUNNING".equals(status) || message != null) {
                return;
            }
            status = "COMPLETED";
            currentAgent = null;
            message = null;
            revokeCredential();
        }

        void fail(String reason) {
            Process child;
            synchronized (this) {
                if ("COMPLETED".equals(status) || "FAILED".equals(status)) return;
                markFailed(reason);
                child = process;
            }
            requestTermination(child);
        }

        synchronized boolean isRunning() {
            return "RUNNING".equals(status);
        }

        void continueRound() {
            Process child = null;
            String failure = null;
            synchronized (this) {
                if (!"PAUSED".equals(status)) {
                    throw new AgentRunConflictException("The learned-agent run is not paused.");
                }
                try {
                    if (process == null || !process.isAlive()) {
                        failure = "The learned-agent process is no longer available to continue.";
                        markFailed(failure);
                    } else {
                        process.getOutputStream().write("CONTINUE\n".getBytes(StandardCharsets.UTF_8));
                        process.getOutputStream().flush();
                        status = "RUNNING";
                        pausedAfterRound = null;
                    }
                } catch (IOException | RuntimeException error) {
                    failure = "Could not resume the learned-agent process.";
                    markFailed(failure);
                    child = process;
                }
            }
            if (failure != null) {
                requestTermination(child);
                throw new AgentRunConflictException(failure);
            }
        }

        void cancel() {
            Process child;
            synchronized (this) {
                if (!("RUNNING".equals(status) || "PAUSED".equals(status))) {
                    throw new AgentRunConflictException("Only an active learned-agent run can be cancelled.");
                }
                markFailed("Learned-agent run cancelled by the user.");
                child = process;
            }
            requestTermination(child);
        }

        private void markFailed(String reason) {
            status = "FAILED";
            currentAgent = null;
            message = sanitize(reason);
            revokeCredential();
        }

        private void requestTermination(Process child) {
            if (child == null || !terminationRequested.compareAndSet(false, true)) return;
            try {
                if (!child.isAlive()) return;
                child.destroy();
            } catch (RuntimeException error) {
                forceStop(child);
                return;
            }
            Thread forceStop = new Thread(() -> {
                try {
                    if (!child.waitFor(2, TimeUnit.SECONDS)) child.destroyForcibly();
                } catch (InterruptedException error) {
                    Thread.currentThread().interrupt();
                    child.destroyForcibly();
                } catch (RuntimeException error) {
                    child.destroyForcibly();
                }
            }, "agent-run-terminate-" + runId);
            forceStop.setDaemon(true);
            forceStop.start();
        }

        private void forceStop(Process child) {
            try {
                child.destroyForcibly();
            } catch (RuntimeException ignored) {
                // Credential revocation and terminal state remain committed even if OS termination fails.
            }
        }

        private void revokeCredential() {
            if (credentialService != null) credentialService.revokeRun(runId);
        }

        synchronized AgentRunResponse snapshot() {
            return new AgentRunResponse(
                    runId, scenarioId, status, currentAgent, pausedAfterRound,
                    latestAction == null ? null : latestAction.deepCopy(),
                    scenarioState == null ? null : scenarioState.deepCopy(),
                    latestEvidence == null ? null : latestEvidence.deepCopy(),
                    finalState == null ? null : finalState.deepCopy(),
                    actionsAttempted, message, List.copyOf(events)
            );
        }
    }

    public static class AgentRunNotFoundException extends RuntimeException {
        public AgentRunNotFoundException(String message) {
            super(message);
        }
    }

    public static class AgentRunConflictException extends RuntimeException {
        public AgentRunConflictException(String message) {
            super(message);
        }
    }
}
