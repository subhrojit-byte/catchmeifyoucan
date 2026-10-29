package catchmeifyoucan.service;

import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Optional;
import java.util.Base64;
import java.util.Arrays;
import java.util.Map;
import java.util.function.Supplier;
import java.util.function.LongSupplier;
import java.util.concurrent.ConcurrentHashMap;

/** Issues short-lived, single-run bearer credentials for one fraudster operation. */
@Service
public class FraudsterRunCredentialService {
    private static final Duration MAX_LIFETIME = Duration.ofDays(1);
    public static final String ROLE = "FRAUDSTER";
    public static final String OPERATION = "FRAUDSTER_PRIVATE_CONTEXT_PROBE";
    public static final String PREFLIGHT_OPERATION = "INVESTIGATOR_TRAINING_ROUTE_PREFLIGHT";
    public static final String ENVIRONMENT_VARIABLE = "CATCHME_FRAUDSTER_RUN_CREDENTIAL";
    public static final String RUN_ID_ENVIRONMENT_VARIABLE = "CATCHME_FRAUDSTER_RUN_ID";
    public static final String HEADER = "X-Fraudster-Run-Credential";
    public static final String RUN_ID_HEADER = "X-Fraudster-Run-ID";
    private static final int TOKEN_BYTES = 32;

    private final SecureRandom secureRandom;
    private final Clock clock;
    // Credential validity uses monotonic time so wall-clock adjustments cannot shorten or extend a run.
    private final LongSupplier nanoClock;
    private final Duration lifetime;
    private final Map<String, Grant> grantsByDigest = new ConcurrentHashMap<>();

    public FraudsterRunCredentialService() {
        this(new SecureRandom(), Clock.systemUTC(), Duration.ofMinutes(5), System::nanoTime);
    }

    FraudsterRunCredentialService(SecureRandom secureRandom, Clock clock, Duration lifetime) {
        this(secureRandom, clock, lifetime, System::nanoTime);
    }

    FraudsterRunCredentialService(SecureRandom secureRandom, Clock clock, Duration lifetime, LongSupplier nanoClock) {
        if (lifetime == null || lifetime.isZero() || lifetime.isNegative()) {
            throw new IllegalArgumentException("Credential lifetime must be positive.");
        }
        this.secureRandom = secureRandom;
        this.clock = clock;
        this.lifetime = lifetime;
        this.nanoClock = nanoClock;
    }

    /** The raw value is returned once for child-process delivery; only its digest is retained. */
    public String issue(long scenarioId, String runId) {
        return issue(scenarioId, runId, lifetime);
    }

    /** Issue a run-bounded grant; callers must keep the requested lifetime within their run policy. */
    public String issue(long scenarioId, String runId, Duration runLifetime) {
        return issueForRun(scenarioId, runId, runLifetime).token();
    }

    IssuedCredential issueForRun(long scenarioId, String runId, Duration runLifetime) {
        return issueForRun(scenarioId, runId, ROLE, OPERATION, runLifetime);
    }

    IssuedCredential issueForPreflight(long scenarioId, String preflightRunId) {
        return issueForRun(scenarioId, preflightRunId, ROLE, PREFLIGHT_OPERATION, lifetime);
    }

    private IssuedCredential issueForRun(long scenarioId, String runId, String role,
                                         String operation, Duration runLifetime) {
        if (scenarioId <= 0 || runId == null || runId.isBlank()) {
            throw new IllegalArgumentException("A valid scenario and run scope are required.");
        }
        if (runLifetime == null || runLifetime.isZero() || runLifetime.isNegative()
                || runLifetime.compareTo(MAX_LIFETIME) > 0) {
            throw new IllegalArgumentException("Credential lifetime must be positive and no longer than 24 hours.");
        }
        byte[] tokenBytes = new byte[TOKEN_BYTES];
        String token;
        String digest;
        Instant expiresAt;
        long expiresAtNanos;
        do {
            secureRandom.nextBytes(tokenBytes);
            token = Base64.getUrlEncoder().withoutPadding().encodeToString(tokenBytes);
            digest = digest(token);
            expiresAt = clock.instant().plus(runLifetime);
            expiresAtNanos = nanoClock.getAsLong() + runLifetime.toNanos();
        } while (grantsByDigest.putIfAbsent(digest, new Grant(
                scenarioId, runId, role, operation, expiresAtNanos)) != null);
        Arrays.fill(tokenBytes, (byte) 0);
        return new IssuedCredential(token, expiresAt, expiresAtNanos);
    }

    long remainingNanos(IssuedCredential issued) {
        if (issued == null) return 0;
        long remaining = issued.expiresAtNanos() - nanoClock.getAsLong();
        return Math.max(remaining, 0);
    }

    static void attachToChildEnvironment(ProcessBuilder builder, String token, String runId) {
        if (builder == null || token == null || token.isBlank() || runId == null || runId.isBlank()) {
            throw new IllegalArgumentException("A valid child process and run credential are required.");
        }
        builder.environment().put(ENVIRONMENT_VARIABLE, token);
        builder.environment().put(RUN_ID_ENVIRONMENT_VARIABLE, runId);
    }

    /** A standalone check only; protected work must use {@link #withAuthorization}. */
    public boolean authorizes(
            String token,
            long scenarioId,
            String runId,
            String role,
            String operation) {
        return withAuthorization(token, scenarioId, runId, role, operation, () -> Boolean.TRUE)
                .orElse(false);
    }

    /**
     * Serializes the protected operation with revocation for this grant only. If the operation
     * acquires the grant monitor first, it has begun and revocation waits for it to finish. If
     * revocation removes the grant first, the operation is rejected. Returned data cannot be
     * recalled after an operation that began first has completed. The supplier must not call
     * back into AgentRunService lifecycle methods: terminal transitions hold the run monitor
     * while revoking grants, so that reverse lock order would deadlock.
     */
    public <T> Optional<T> withAuthorization(
            String token,
            long scenarioId,
            String runId,
            String role,
            String operation,
            Supplier<T> protectedOperation) {
        if (token == null || token.isBlank() || scenarioId <= 0
                || runId == null || role == null || operation == null || protectedOperation == null) {
            return Optional.empty();
        }
        String digest;
        try {
            digest = digest(token);
        } catch (IllegalArgumentException error) {
            return Optional.empty();
        }
        Grant grant = grantsByDigest.get(digest);
        if (grant == null) return Optional.empty();
        synchronized (grant) {
            if (grantsByDigest.get(digest) != grant) {
                return Optional.empty();
            }
            if (grant.expiresAtNanos() - nanoClock.getAsLong() <= 0) {
                grantsByDigest.remove(digest, grant);
                return Optional.empty();
            }
            if (grant.scenarioId() != scenarioId || !grant.runId().equals(runId)
                    || !grant.role().equals(role) || !grant.operation().equals(operation)) {
                return Optional.empty();
            }
            return Optional.ofNullable(protectedOperation.get());
        }
    }

    public void revoke(String token) {
        if (token == null || token.isBlank()) {
            return;
        }
        try {
            String digest = digest(token);
            Grant grant = grantsByDigest.get(digest);
            revoke(digest, grant);
        } catch (IllegalArgumentException ignored) {
            // Invalid credentials have no grant to revoke.
        }
    }

    /** Revokes any grant for a run without retaining or looking up its plaintext token. */
    public void revokeRun(String runId) {
        if (runId == null || runId.isBlank()) {
            return;
        }
        grantsByDigest.forEach((digest, grant) -> {
            if (runId.equals(grant.runId())) revoke(digest, grant);
        });
    }

    private void revoke(String digest, Grant grant) {
        if (grant == null) return;
        synchronized (grant) {
            grantsByDigest.remove(digest, grant);
        }
    }

    private static String digest(String token) {
        try {
            byte[] hash = MessageDigest.getInstance("SHA-256")
                    .digest(token.getBytes(StandardCharsets.UTF_8));
            return Base64.getEncoder().encodeToString(hash);
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException("SHA-256 is unavailable.", error);
        }
    }

    private record Grant(long scenarioId, String runId, String role, String operation, long expiresAtNanos) {
    }

    record IssuedCredential(String token, Instant expiresAt, long expiresAtNanos) { }
}
