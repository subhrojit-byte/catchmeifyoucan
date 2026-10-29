package catchmeifyoucan.service;

import tools.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class AgentRunServiceTest {
    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void actionAndTerminalEventsUpdateTheRunSnapshot() throws Exception {
        AgentRunService.RunRecord run = new AgentRunService.RunRecord("run-1", 22L);
        run.accept(mapper.readTree("""
                {"event_type":"action","agent":"FRAUDSTER","action":{"action_type":"DIRECT_TRANSFER"},
                 "state":{"id":22,"status":"ACTIVE","turn":"INVESTIGATOR"}}
                """));

        var during = run.snapshot();
        assertEquals("RUNNING", during.status());
        assertEquals("FRAUDSTER", during.currentAgent());
        assertEquals("DIRECT_TRANSFER", during.latestAction().path("action_type").asText());
        assertEquals("INVESTIGATOR", during.scenarioState().path("turn").asText());

        run.accept(mapper.readTree("""
                {"event_type":"episode_result","episode_class":"completed","actions_attempted":7,
                 "final_state":{"id":22,"status":"MAX_TURNS_REACHED"}}
                """));
        assertTrue(run.hasValidTerminalResult());
        run.complete();
        var completed = run.snapshot();
        assertEquals("COMPLETED", completed.status());
        assertEquals(7, completed.actionsAttempted());
        assertEquals("MAX_TURNS_REACHED", completed.finalState().path("status").asText());
        assertFalse(completed.events().isEmpty());
    }

    @Test
    void failuresAreSanitizedAndRemainFailed() throws Exception {
        AgentRunService.RunRecord run = new AgentRunService.RunRecord("run-2", 23L);
        run.accept(mapper.readTree("""
                {"event_type":"runner_error","message":"Could not connect to postgresql://user:secret@host/db"}
                """));
        run.fail(run.snapshot().message());
        var failed = run.snapshot();
        assertEquals("FAILED", failed.status());
        assertTrue(failed.message().contains("database URL redacted"));
        assertFalse(failed.message().contains("secret"));
        run.accept(mapper.readTree("""
                {"event_type":"action","agent":"FRAUDSTER","action":{"action_type":"WAIT"}}
                """));
        assertNull(run.snapshot().latestAction());
    }

    @Test
    void runnerDiagnosticsAreNotExposedInRunEvents() throws Exception {
        AgentRunService.RunRecord run = new AgentRunService.RunRecord("run-diagnostic", 23L);
        run.accept(mapper.readTree("""
                {"event_type":"runner_diagnostic","diagnostic":{"stage":"fetch",
                 "exception_type":"InsufficientPrivilege","sqlstate":"42501"}}
                """));

        assertTrue(run.snapshot().events().isEmpty());
        assertNull(run.snapshot().message());
    }

    @Test
    void invalidProgressDataCannotBeOverwrittenByTerminalResult() throws Exception {
        AgentRunService.RunRecord run = new AgentRunService.RunRecord("run-3", 24L);
        run.fail("Python runner emitted malformed progress data.");
        run.accept(mapper.readTree("""
                {"event_type":"episode_result","final_state":{"id":24,"status":"COMPLETED"}}
                """));
        assertFalse(run.hasValidTerminalResult());
        run.complete();
        assertEquals("FAILED", run.snapshot().status());
    }

    @Test
    void trainingRunRequiresAValidatedTrainingResultBeforeTerminalCompletion() throws Exception {
        AgentRunService.RunRecord run = new AgentRunService.RunRecord(
                "training-run", 25L, null, true,
                Path.of("fraudster-trained-run-training-run.json"),
                Path.of("investigator-trained-run-training-run.json"));
        run.accept(mapper.readTree("""
                {"event_type":"episode_result","episode_class":"completed",
                 "final_state":{"id":25,"status":"COMPLETED"}}
                """));

        assertFalse(run.hasValidTerminalResult());
        run.accept(mapper.readTree("""
                {"event_type":"training_result","scenario_id":25,"episode_count":1,
                 "episode_completed":true,"fraudster_transition_count":1,
                 "fraudster_training_steps":1,
                 "fraudster_checkpoint":"fraudster-trained-run-training-run.json",
                 "investigator_checkpoint":"investigator-trained-run-training-run.json"}
                """));

        assertTrue(run.hasValidTerminalResult());
    }

    @Test
    void roundPauseIsObservableAndResumeEventReturnsRunToRunning() throws Exception {
        AgentRunService.RunRecord run = new AgentRunService.RunRecord("run-4", 25L);
        run.accept(mapper.readTree("""
                {"event_type":"round_paused","round_number":1,
                 "state":{"id":25,"status":"ACTIVE","turn":"FRAUDSTER"}}
                """));

        assertEquals("PAUSED", run.snapshot().status());
        assertEquals(1, run.snapshot().pausedAfterRound());
        assertEquals("FRAUDSTER", run.snapshot().scenarioState().path("turn").asText());

        run.accept(mapper.readTree("""
                {"event_type":"round_resumed","round_number":1}
                """));

        assertEquals("RUNNING", run.snapshot().status());
        assertNull(run.snapshot().pausedAfterRound());
    }
}
