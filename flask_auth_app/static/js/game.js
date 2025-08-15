/**
 * Șeptică - Game Interactivity Script
 * Handles card interactions, animations, and game mechanics
 */

// Initialize socket connection
const socket = io();
let myCards = [];
let currentTrick = [];
let isMyTurn = false;
let myPosition = null;
let lobbyCode = null;
let gameState = null;

document.addEventListener('DOMContentLoaded', function() {
    // Get lobby code from hidden input
    lobbyCode = document.getElementById('lobby-code').value;
    if (!lobbyCode) {
        console.error('No lobby code found!');
        return;
    }

    // Remove existing interval if any
    if (window.turnInterval) {
        clearInterval(window.turnInterval);
    }

    // Join game room and initialize
    socket.emit('join_lobby_room', { lobby_code: lobbyCode });
    socket.emit('initialize_game', { lobby_code: lobbyCode });

    // Socket event listeners
    socket.on('game_state_update', handleGameStateUpdate);
    socket.on('game_error', handleGameError);
});

function handleGameStateUpdate(state) {
    console.log('Received game state:', state);
    if (!state) return;

    gameState = state;
    myCards = state.hand || [];
    currentTrick = state.current_trick || [];
    isMyTurn = state.current_player === state.position;
    myPosition = state.position;

    updateGameDisplay(state);
}

function handleGameError(data) {
    console.error('Game error:', data.message);
    alert(data.message);
}

function updateGameDisplay(state) {
    try {
        // Update scores and trump
        updateScoresAndTrump(state);
        
        // Update current player's hand (face-up)
        updatePlayerHand(state.hand || []);
        
        // Update opponent hands (face-down cards)
        updateOpponentHands(state);
        
        // Update player avatars and turn indicators
        updatePlayerAvatars(state);
        
        // Update center pile
        updateCenterPile(state.current_trick || []);
        
    } catch (error) {
        console.error('Error updating game display:', error);
    }
}

function updateScoresAndTrump(state) {
    const team1Score = document.querySelector('.team1-score');
    const team2Score = document.querySelector('.team2-score');
    const trumpSuit = document.querySelector('.trump-suit');
    const deckCount = document.querySelector('.cards-in-deck');

    if (team1Score) team1Score.textContent = state.scores?.[0] || 0;
    if (team2Score) team2Score.textContent = state.scores?.[1] || 0;
    if (trumpSuit) trumpSuit.innerHTML = `Trump: ${getSuitSymbol(state.trump_suit)}`;
    if (deckCount) deckCount.textContent = state.cards_in_deck || 0;
}

function updatePlayerHand(cards) {
    const playerHand = document.querySelector('#player-0-hand') || document.querySelector('.player-hand.me');
    if (!playerHand) return;

    playerHand.innerHTML = '';
    cards.forEach((card, index) => {
        const cardElement = createCardElement(card, index);
        // Only allow card interaction if it's player's turn
        cardElement.classList.toggle('playable', isMyTurn);
        playerHand.appendChild(cardElement);
    });
}

function updateOpponentHands(state) {
    // Show face-down cards for other players
    const handSizes = state.hand_sizes || [4, 4, 4, 4];
    
    for (let i = 1; i <= 3; i++) {
        const handElement = document.querySelector(`#player-${i}-hand`);
        if (!handElement) continue;
        
        handElement.innerHTML = '';
        
        // Show face-down cards based on hand size
        const handSize = handSizes[(myPosition + i) % 4] || 0;
        for (let j = 0; j < handSize; j++) {
            const cardBack = createCardBack();
            handElement.appendChild(cardBack);
        }
    }
}

function updatePlayerAvatars(state) {
    // Clear all current-turn classes
    document.querySelectorAll('.player-avatar').forEach(avatar => {
        avatar.classList.remove('current-turn');
    });
    
    // Add current-turn class to the active player
    const currentPlayerRelativePos = (state.current_player - myPosition + 4) % 4;
    const currentPlayerAvatar = document.querySelector(`#player-${currentPlayerRelativePos}-avatar`);
    if (currentPlayerAvatar) {
        currentPlayerAvatar.classList.add('current-turn');
    }
    
    // Update player names if available
    if (state.player_names) {
        for (let i = 0; i < 4; i++) {
            const avatar = document.querySelector(`#player-${i}-avatar`);
            if (avatar && state.player_names[(myPosition + i) % 4]) {
                avatar.textContent = state.player_names[(myPosition + i) % 4];
            }
        }
    }
}

function updateCenterPile(currentTrick) {
    const centerPile = document.querySelector('.center-pile');
    if (!centerPile) return;

    centerPile.innerHTML = '';
    currentTrick.forEach((playedCard, index) => {
        const [position, card] = playedCard;
        const cardElement = createCardElement(card, undefined, true);
        
        // Position cards in center based on which player played them
        const relativePosition = (position - myPosition + 4) % 4;
        const angle = relativePosition * 90; // 0°, 90°, 180°, 270°
        const distance = 50; // Distance from center
        
        cardElement.style.position = 'absolute';
        cardElement.style.left = '50%';
        cardElement.style.top = '50%';
        cardElement.style.transform = `translate(-50%, -50%) rotate(${angle}deg) translateY(-${distance}px) rotate(-${angle}deg)`;
        cardElement.style.zIndex = index + 1;
        
        centerPile.appendChild(cardElement);
    });
}

function createCardElement(card, index, isCenter = false) {
    const cardDiv = document.createElement('div');
    cardDiv.className = `playing-card ${card.suit}`;
    
    cardDiv.innerHTML = `
        <div class="card-value">${card.value}</div>
        <div class="card-suit">${getSuitSymbol(card.suit)}</div>
    `;
    
    if (!isCenter && index !== undefined) {
        // Only add click handler if it's player's turn
        if (isMyTurn) {
            cardDiv.classList.add('playable');
            cardDiv.onclick = () => playCard(index);
        }
    }
    
    return cardDiv;
}

function createCardBack() {
    const cardDiv = document.createElement('div');
    cardDiv.className = 'playing-card card-back';
    return cardDiv;
}

function playCard(index) {
    if (!isMyTurn || !gameState) return;
    
    socket.emit('play_card', {
        lobby_code: lobbyCode,
        card_index: index
    });
}

function getSuitSymbol(suit) {
    const symbols = {
        'hearts': '♥',
        'diamonds': '♦',
        'clubs': '♣',
        'spades': '♠'
    };
    return symbols[suit] || suit;
}