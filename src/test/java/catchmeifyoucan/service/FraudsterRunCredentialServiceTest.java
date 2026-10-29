package catchmeifyoucan.service;

import org.junit.jupiter.api.Test;

import java.security.SecureRandom;
import java.time.Clock;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class FraudsterRunCredentialServiceTest {
    private static final String ROLE = FraudsterRunCredentialService.ROLE;
    private static final String OPERATION = FraudsterRunCredentialService.OPERATION;

    @Test
    void credentialAuthorizesOnlyItsScenarioRunRoleAndOperation() {
        var service = service(Duration.ofMinutes(1));
        String credential = service.issue(10, "run-a");

        assertTrue(service.authorizes(credential, 10, "run-a", ROLE, OPERATION));
        assertFalse(service.authorizes(null, 10, "run-a", ROLE, OPERATION));
        assertFalse(service.authorizes("malformed", 10, "run-a", ROLE, OPERATION));
        assertFalse(service.authorizes("random-invalid-value", 10, "run-a", ROLE, OPERATION));
        assertFalse(service.authorizes(credential, 11, "run-a", ROLE, OPERATION));
        assertFalse(service.authorizes(credential, 10, "run-b", ROLE, OPERATION));
        assertFalse(service.authorizes(credential, 10, "run-a", "INVESTIGATOR", OPERATION));
        assertFalse(service.authorizes(credential, 10, "run-a", ROLE, "OTHER_OPERATION"));
    }

    @Test
    void preflightCredentialIsBoundToItsScenarioRunRoleAndOperation() {
        var service = service(Duration.ofMinutes(1));
        String credential = service.issueForPreflight(342, "preflight-run").token();
        AtomicBoolean protectedOperationCalled = new AtomicBoolean();

        assertTrue(service.withAuthorization(credential, 342, "preflight-run", ROLE,
                FraudsterRunCredentialService.PREFLIGHT_OPERATION, () -> {
                    protectedOperationCalled.set(true);
                    return Boolean.TRUE;
                }).orElse(false));
        assertTrue(protectedOperationCalled.get());

        protectedOperationCalled.set(false);
        assertFalse(service.withAuthorization(credential, 343, "preflight-run", ROLE,
                FraudsterRunCredentialService.PREFLIGHT_OPERATION, () -> {
                    protectedOperationCalled.set(true);
                    return Boolean.TRUE;
                }).isPresent());
        assertFalse(protectedOperationCalled.get());
        assertFalse(service.authorizes(credential, 342, "preflight-run", ROLE, OPERATION));
        service.revokeRun("preflight-run");
    }

    @Test
    void expiredAndRevokedCredentialsAreRejected() {
        AtomicLong ticker = new AtomicLong();
        var service = new FraudsterRunCredentialService(
                new SecureRandom(), Clock.systemUTC(), Duration.ofSeconds(2), ticker::get);
        String expired = service.issue(20, "run-expired");
        ticker.addAndGet(Duration.ofSeconds(3).toNanos());
        assertFalse(service.authorizes(expired, 20, "run-expired", ROLE, OPERATION));

        String revoked = service.issue(21, "run-revoked");
        service.revoke(revoked);
        assertFalse(service.authorizes(revoked, 21, "run-revoked", ROLE, OPERATION));
    }

    @Test
    void separatelyIssuedRunCredentialsCannotBeReplayedAcrossRuns() {
        var service = service(Duration.ofMinutes(1));
        String firstRun = service.issue(30, "run-first");
        String secondRun = service.issue(30, "run-second");

        assertFalse(service.authorizes(firstRun, 30, "run-second", ROLE, OPERATION));
        assertFalse(service.authorizes(secondRun, 30, "run-first", ROLE, OPERATION));
        assertTrue(service.authorizes(firstRun, 30, "run-first", ROLE, OPERATION));
        service.revoke(firstRun);
        assertFalse(service.authorizes(firstRun, 30, "run-first", ROLE, OPERATION));
    }

    @Test
    void credentialIsDeliveredOnlyThroughChildEnvironmentNotCommandArguments() {
        var service = service(Duration.ofMinutes(1));
        String credential = service.issue(40, "run-40");
        ProcessBuilder builder = new ProcessBuilder("python", "runner.py", "--scenario-id", "40");

        FraudsterRunCredentialService.attachToChildEnvironment(builder, credential, "run-40");

        assertEquals(credential, builder.environment().get(
                FraudsterRunCredentialService.ENVIRONMENT_VARIABLE));
        assertEquals("run-40", builder.environment().get(
                FraudsterRunCredentialService.RUN_ID_ENVIRONMENT_VARIABLE));
        assertFalse(String.join(" ", builder.command()).contains(credential));
        service.revoke(credential);
    }

    @Test
    void protectedOperationAndRevocationHaveOnePerGrantOrdering() throws Exception {
        var service = service(Duration.ofMinutes(1));
        String credential = service.issue(50, "run-order");
        CountDownLatch operationEntered = new CountDownLatch(1);
        CountDownLatch allowOperationToFinish = new CountDownLatch(1);
        CountDownLatch revokeAttempted = new CountDownLatch(1);
        CountDownLatch revokeFinished = new CountDownLatch(1);
        AtomicReference<java.util.Optional<String>> operationResult = new AtomicReference<>();

        Thread operation = new Thread(() -> operationResult.set(service.withAuthorization(
                credential, 50, "run-order", ROLE, OPERATION, () -> {
                    operationEntered.countDown();
                    await(allowOperationToFinish);
                    return "completed";
                })));
        operation.start();
        assertTrue(operationEntered.await(2, TimeUnit.SECONDS));

        Thread revoker = new Thread(() -> {
            revokeAttempted.countDown();
            service.revoke(credential);
            revokeFinished.countDown();
        });
        revoker.start();
        assertTrue(revokeAttempted.await(2, TimeUnit.SECONDS));
        awaitBlocked(revoker);
        assertEquals(1L, revokeFinished.getCount());

        allowOperationToFinish.countDown();
        operation.join(2_000);
        revoker.join(2_000);
        assertFalse(operation.isAlive());
        assertFalse(revoker.isAlive());
        assertEquals(java.util.Optional.of("completed"), operationResult.get());
        assertFalse(service.withAuthorization(credential, 50, "run-order", ROLE, OPERATION, () -> "late").isPresent());
    }

    @Test
    void concurrentAuthorizationCannotStartAfterRevocationWins() throws Exception {
        var service = service(Duration.ofMinutes(1));
        String credential = service.issue(51, "run-race");
        CyclicBarrier start = new CyclicBarrier(3);
        CountDownLatch revokeFinished = new CountDownLatch(1);
        AtomicBoolean operationStartedAfterRevoke = new AtomicBoolean();
        AtomicReference<java.util.Optional<String>> result = new AtomicReference<>();

        Thread operation = new Thread(() -> {
            await(start);
            result.set(service.withAuthorization(credential, 51, "run-race", ROLE, OPERATION, () -> {
                if (revokeFinished.getCount() == 0) operationStartedAfterRevoke.set(true);
                return "started";
            }));
        });
        Thread revoker = new Thread(() -> {
            await(start);
            service.revoke(credential);
            revokeFinished.countDown();
        });
        operation.start();
        revoker.start();
        start.await(2, TimeUnit.SECONDS);
        operation.join(2_000);
        revoker.join(2_000);

        assertFalse(operation.isAlive());
        assertFalse(revoker.isAlive());
        assertFalse(operationStartedAfterRevoke.get());
        assertFalse(service.authorizes(credential, 51, "run-race", ROLE, OPERATION));
    }

    @Test
    void credentialWindowAcceptsTimeoutUpToTwentyFourHoursAndRejectsMore() {
        AtomicLong ticker = new AtomicLong();
        var service = new FraudsterRunCredentialService(
                new SecureRandom(), Clock.systemUTC(), Duration.ofMinutes(5), ticker::get);
        String max = service.issue(52, "run-max", Duration.ofHours(24));
        ticker.addAndGet(Duration.ofHours(24).toNanos() - 1);
        assertTrue(service.authorizes(max, 52, "run-max", ROLE, OPERATION));
        ticker.incrementAndGet();
        assertFalse(service.authorizes(max, 52, "run-max", ROLE, OPERATION));
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class,
                () -> service.issue(52, "run-too-long", Duration.ofHours(24).plusNanos(1)));
    }

    private static void await(CountDownLatch latch) {
        try {
            if (!latch.await(2, TimeUnit.SECONDS)) throw new AssertionError("test synchronization timed out");
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new AssertionError(error);
        }
    }

    private static void await(CyclicBarrier barrier) {
        try {
            barrier.await(2, TimeUnit.SECONDS);
        } catch (Exception error) {
            throw new AssertionError(error);
        }
    }

    private static void awaitBlocked(Thread thread) {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(2);
        while (thread.getState() != Thread.State.BLOCKED && System.nanoTime() < deadline) {
            Thread.yield();
        }
        assertEquals(Thread.State.BLOCKED, thread.getState());
    }

    private static FraudsterRunCredentialService service(Duration lifetime) {
        return new FraudsterRunCredentialService(new SecureRandom(), Clock.systemUTC(), lifetime);
    }

}
