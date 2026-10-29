package catchmeifyoucan.entity;

import com.fasterxml.jackson.annotation.JsonIgnore;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.util.ArrayList;
import java.util.List;

@Getter
@Entity
@Table(name = "fraud_actions")
public class FraudAction {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Setter
    @JsonIgnore
    @ManyToOne
    @JoinColumn(name = "scenario_id", nullable = false)
    private FraudScenario scenario;

    @Setter
    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private FraudActionType actionType;

    @Setter
    @ManyToOne
    @JoinColumn(name = "source_position_id", nullable = false)
    private FraudPosition sourcePosition;

    @Setter
    @Column(nullable = false)
    private int step;

    /** Nullable for compatibility with actions persisted before background ticks. */
    @Setter
    @Column(name = "background_transactions_generated")
    private Boolean backgroundTransactionsGenerated = false;

    /** Prevents two concurrent retries from both creating a background tick. */
    @Version
    @Column(name = "version")
    private Long version;

    @OneToMany(
            mappedBy = "action",
            cascade = CascadeType.ALL,
            orphanRemoval = true
    )
    private List<FraudActionTarget> targets =
            new ArrayList<>();

    public FraudAction() {
    }
}
